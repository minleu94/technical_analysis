"""正式 portfolio ledger 的唯讀 custody 與因果 T-1 state replay。

這個模組只接受已完成、可重算 hash 的正式 ledger manifest。它不會從
Teacher target、研究 shadow 或 Advice 推導 portfolio state；缺少正式 ledger
時，呼叫端必須繼續使用明示的 cash-only fallback 並維持 formal gate blocked。

Ledger 的 SQLite 只保存每日 transition，而非每一筆 ML sample，因此驗證時
可以維持 bounded state。所有權重、turnover 與 chain 欄位均使用整數 bp；不在
金融計算邊界引入裸 float。
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import date
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Sequence

from ml_module.allocation_contracts import (
    AllocationWeightContract,
    CausalPortfolioState,
)


FORMAL_PORTFOLIO_LEDGER_SCHEMA_VERSION = "causal-portfolio-ledger.v1"
FORMAL_PORTFOLIO_LEDGER_TRANSITION_SCHEMA_VERSION = (
    "causal-portfolio-ledger-transition.v1"
)
PORTFOLIO_STATE_REPLAY_SCHEMA_VERSION = "causal-portfolio-state-replay-v1"
_SHA256_PREFIX = "sha256:"
_ZERO_SHA256 = _SHA256_PREFIX + ("0" * 64)

_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "formal_source_only",
        "research_only",
        "formal_consumer_compatible",
        "promotion_eligible",
        "transition_schema_version",
        "sqlite_path",
        "sqlite_file_hash",
        "policy_hash",
        "decision_dates",
        "decision_date_count",
        "non_cash_state_day_count",
        "transition_chain_hash",
        "future_teacher_target_used",
        "same_day_advice_used",
        "ledger_manifest_hash",
        "manifest_hash",
    }
)
_TRANSITION_COLUMNS = frozenset(
    {
        "decision_date",
        "input_state_json",
        "desired_weights_json",
        "output_state_json",
        "feature_input_hash",
        "buy_turnover_bp",
        "sell_turnover_bp",
        "canonical_turnover_bp",
        "estimated_cost_bp",
        "add_count",
        "reduce_count",
        "transition_hash",
        "chain_hash",
    }
)


@dataclass(frozen=True)
class FormalPortfolioStateReplayEntry:
    decision_date: str
    transition_hash: str
    state: CausalPortfolioState


@dataclass(frozen=True)
class FormalPortfolioStateReplay:
    """由正式 ledger 的 input state 建立的決策日前 replay。"""

    entries: tuple[FormalPortfolioStateReplayEntry, ...]
    ledger_manifest_hash: str
    ledger_manifest_file_hash: str
    ledger_file_hash: str
    ledger_manifest_path: Path
    ledger_file_path: Path
    policy_hash: str
    transition_chain_hash: str
    non_cash_state_day_count: int
    decision_dates: tuple[str, ...] = field(init=False, repr=False)
    cash_only_fallback: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        decision_dates = tuple(item.decision_date for item in self.entries)
        if decision_dates != tuple(sorted(set(decision_dates))):
            raise ValueError(
                "formal portfolio ledger decision dates must be unique and sorted"
            )
        if not self.entries:
            raise ValueError("formal portfolio ledger cannot be empty")
        if self.non_cash_state_day_count <= 0:
            raise ValueError(
                "formal portfolio ledger must contain a non-cash input state"
            )
        object.__setattr__(self, "decision_dates", decision_dates)

    def state_for(self, decision_date: str) -> CausalPortfolioState:
        index = bisect_left(self.decision_dates, decision_date)
        if (
            index < len(self.decision_dates)
            and self.decision_dates[index] == decision_date
        ):
            return self.entries[index].state
        raise KeyError(
            f"formal portfolio ledger misses decision date: {decision_date}"
        )

    def custody_payload(self) -> dict[str, object]:
        return {
            "schema_version": PORTFOLIO_STATE_REPLAY_SCHEMA_VERSION,
            "mode": "per_decision_t_minus_1_ledger",
            "ledger_present": True,
            "ledger_manifest_hash": self.ledger_manifest_hash,
            "ledger_manifest_file_hash": self.ledger_manifest_file_hash,
            "ledger_file_hash": self.ledger_file_hash,
            "ledger_manifest_path": str(self.ledger_manifest_path),
            "ledger_file_path": str(self.ledger_file_path),
            "policy_hash": self.policy_hash,
            "transition_chain_hash": self.transition_chain_hash,
            "transition_count": len(self.entries),
            "non_cash_state_day_count": self.non_cash_state_day_count,
            "cash_only_fallback": False,
            "teacher_targets_replayed_into_state": False,
            "turnover_observed": True,
            "cooldown_observed": True,
            "turnover_learning_claim_allowed": True,
            "cooldown_learning_claim_allowed": True,
        }


def load_formal_portfolio_state_ledger(
    manifest_path: Path,
    *,
    calendar: Sequence[str] | None = None,
    decision_dates: Sequence[str] | None = None,
) -> FormalPortfolioStateReplay:
    """讀取並驗證正式 ledger；任何 custody 不一致都直接拒絕。

    ``calendar`` 與 ``decision_dates`` 由 assembler 提供時，會額外驗證每個
    input state 正好是該決策日的前一個 benchmark session，且 ledger 覆蓋
    全部 assembly decision dates。若 OOS consumer 只需要驗證 ledger 本身，
    可以省略兩者，但仍會驗證 transition chain 與 state hash。
    """

    resolved_manifest = manifest_path.resolve()
    if not resolved_manifest.is_file():
        raise FileNotFoundError(
            f"formal portfolio ledger manifest is missing: {resolved_manifest}"
        )
    manifest = _read_json(resolved_manifest)
    _validate_manifest(manifest)
    manifest_hash = _required_sha256(manifest.get("manifest_hash"), "manifest_hash")
    body = dict(manifest)
    body.pop("manifest_hash", None)
    if _payload_hash(body) != manifest_hash:
        raise ValueError("formal portfolio ledger manifest hash mismatch")
    manifest_file_hash = _file_hash(resolved_manifest)

    declared_dates = _date_sequence(
        manifest.get("decision_dates"),
        field_name="decision_dates",
    )
    if _required_int(manifest.get("decision_date_count"), "decision_date_count") != len(
        declared_dates
    ):
        raise ValueError("formal portfolio ledger decision_date_count mismatch")
    if decision_dates is not None:
        expected_dates = _date_sequence(
            list(decision_dates),
            field_name="expected_decision_dates",
        )
        if declared_dates != expected_dates:
            raise ValueError(
                "formal portfolio ledger decision dates do not cover assembly dates"
            )

    ledger_text = _required_text(manifest.get("sqlite_path"), "sqlite_path")
    ledger_path = (resolved_manifest.parent / ledger_text).resolve()
    if not ledger_path.is_relative_to(resolved_manifest.parent.resolve()):
        raise ValueError("formal portfolio ledger sqlite path escapes custody root")
    if not ledger_path.is_file():
        raise FileNotFoundError(
            f"formal portfolio ledger sqlite is missing: {ledger_path}"
        )
    ledger_file_hash = _required_sha256(
        manifest.get("sqlite_file_hash"),
        "sqlite_file_hash",
    )
    if _file_hash(ledger_path) != ledger_file_hash:
        raise ValueError("formal portfolio ledger sqlite hash mismatch")

    policy_hash = _required_sha256(manifest.get("policy_hash"), "policy_hash")
    transition_chain_hash = _required_sha256(
        manifest.get("transition_chain_hash"),
        "transition_chain_hash",
    )
    ledger_manifest_hash = _required_sha256(
        manifest.get("ledger_manifest_hash"),
        "ledger_manifest_hash",
    )
    ledger_identity = {
        "schema_version": manifest["schema_version"],
        "transition_schema_version": manifest["transition_schema_version"],
        "sqlite_file_hash": ledger_file_hash,
        "policy_hash": policy_hash,
        "decision_dates": list(declared_dates),
        "decision_date_count": len(declared_dates),
        "non_cash_state_day_count": _required_nonnegative_int(
            manifest.get("non_cash_state_day_count"),
            "non_cash_state_day_count",
        ),
        "transition_chain_hash": transition_chain_hash,
        "future_teacher_target_used": False,
        "same_day_advice_used": False,
    }
    if _payload_hash(ledger_identity) != ledger_manifest_hash:
        raise ValueError("formal portfolio ledger identity hash mismatch")

    calendar_positions = _calendar_positions(calendar)
    entries: list[FormalPortfolioStateReplayEntry] = []
    previous_output_hash = _ZERO_SHA256
    previous_chain_hash = _ZERO_SHA256
    observed_non_cash = 0
    connection = sqlite3.connect(
        f"file:{ledger_path.as_posix()}?mode=ro",
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        columns = {
            str(item[1])
            for item in connection.execute("PRAGMA table_info(transitions)")
        }
        if not _TRANSITION_COLUMNS.issubset(columns):
            raise ValueError("formal portfolio ledger transition schema mismatch")
        cursor = connection.execute(
            """
            SELECT decision_date, input_state_json, desired_weights_json,
                   output_state_json, feature_input_hash,
                   buy_turnover_bp, sell_turnover_bp, canonical_turnover_bp,
                   estimated_cost_bp, add_count, reduce_count,
                   transition_hash, chain_hash
            FROM transitions
            ORDER BY decision_date ASC
            """
        )
        for row in cursor:
            decision_day = _required_text(row["decision_date"], "transition.decision_date")
            if decision_day not in declared_dates:
                raise ValueError(
                    f"formal portfolio ledger has unexpected decision date: {decision_day}"
                )
            if entries and decision_day <= entries[-1].decision_date:
                raise ValueError("formal portfolio ledger dates are not strictly increasing")
            input_state = _state_from_json(
                _required_text(row["input_state_json"], "transition.input_state_json"),
                field_name="transition.input_state",
            )
            output_state = _state_from_json(
                _required_text(row["output_state_json"], "transition.output_state_json"),
                field_name="transition.output_state",
            )
            desired_weights = _weights_from_json(
                _required_text(
                    row["desired_weights_json"],
                    "transition.desired_weights_json",
                ),
                field_name="transition.desired_weights",
            )
            _validate_temporal_state(
                input_state=input_state,
                output_state=output_state,
                decision_day=decision_day,
                calendar_positions=calendar_positions,
            )
            if input_state.state_hash != previous_output_hash and entries:
                raise ValueError(
                    f"formal portfolio ledger state chain mismatch: {decision_day}"
                )
            feature_input_hash = _required_sha256(
                row["feature_input_hash"],
                "transition.feature_input_hash",
            )
            integer_fields = {
                field_name: _required_nonnegative_int(
                    row[field_name],
                    f"transition.{field_name}",
                )
                for field_name in (
                    "buy_turnover_bp",
                    "sell_turnover_bp",
                    "canonical_turnover_bp",
                    "estimated_cost_bp",
                    "add_count",
                    "reduce_count",
                )
            }
            transition_payload = {
                "schema_version": FORMAL_PORTFOLIO_LEDGER_TRANSITION_SCHEMA_VERSION,
                "decision_date": decision_day,
                "input_state_hash": input_state.state_hash,
                "feature_input_hash": feature_input_hash,
                "desired_weights": _weight_payload(desired_weights),
                "output_state_hash": output_state.state_hash,
                **integer_fields,
                "future_teacher_target_used": False,
                "same_day_advice_used": False,
            }
            transition_hash = _required_sha256(
                row["transition_hash"],
                "transition.transition_hash",
            )
            if _payload_hash(transition_payload) != transition_hash:
                raise ValueError(
                    f"formal portfolio ledger transition hash mismatch: {decision_day}"
                )
            expected_chain_hash = _payload_hash(
                {
                    "previous_chain_hash": previous_chain_hash,
                    "transition_hash": transition_hash,
                }
            )
            chain_hash = _required_sha256(row["chain_hash"], "transition.chain_hash")
            if chain_hash != expected_chain_hash:
                raise ValueError(
                    f"formal portfolio ledger chain hash mismatch: {decision_day}"
                )
            if input_state.weights.invested_bp > 0:
                observed_non_cash += 1
            entries.append(
                FormalPortfolioStateReplayEntry(
                    decision_date=decision_day,
                    transition_hash=transition_hash,
                    state=input_state,
                )
            )
            previous_output_hash = output_state.state_hash
            previous_chain_hash = chain_hash
    finally:
        connection.close()

    if tuple(item.decision_date for item in entries) != declared_dates:
        raise ValueError("formal portfolio ledger transition coverage mismatch")
    declared_non_cash = _required_nonnegative_int(
        manifest.get("non_cash_state_day_count"),
        "non_cash_state_day_count",
    )
    if declared_non_cash != observed_non_cash:
        raise ValueError("formal portfolio ledger non-cash count mismatch")
    if previous_chain_hash != transition_chain_hash:
        raise ValueError("formal portfolio ledger final chain hash mismatch")

    return FormalPortfolioStateReplay(
        entries=tuple(entries),
        ledger_manifest_hash=ledger_manifest_hash,
        ledger_manifest_file_hash=manifest_file_hash,
        ledger_file_hash=ledger_file_hash,
        ledger_manifest_path=resolved_manifest,
        ledger_file_path=ledger_path,
        policy_hash=policy_hash,
        transition_chain_hash=transition_chain_hash,
        non_cash_state_day_count=observed_non_cash,
    )


def _validate_manifest(manifest: Mapping[str, object]) -> None:
    if set(manifest) != _MANIFEST_FIELDS:
        raise ValueError("formal portfolio ledger manifest fields mismatch")
    if manifest.get("schema_version") != FORMAL_PORTFOLIO_LEDGER_SCHEMA_VERSION:
        raise ValueError("formal portfolio ledger schema mismatch")
    if manifest.get("status") != "complete":
        raise ValueError("formal portfolio ledger is not complete")
    if manifest.get("formal_source_only") is not True:
        raise ValueError("formal portfolio ledger must be formal_source_only")
    if manifest.get("research_only") is not False:
        raise ValueError("research-only portfolio ledger cannot enter formal path")
    if manifest.get("formal_consumer_compatible") is not True:
        raise ValueError("formal portfolio ledger must be consumer compatible")
    if manifest.get("promotion_eligible") is not False:
        raise ValueError("portfolio ledger is not a promotion artifact")
    if manifest.get("transition_schema_version") != (
        FORMAL_PORTFOLIO_LEDGER_TRANSITION_SCHEMA_VERSION
    ):
        raise ValueError("formal portfolio ledger transition schema mismatch")
    if manifest.get("future_teacher_target_used") is not False:
        raise ValueError("formal portfolio ledger cannot use future teacher targets")
    if manifest.get("same_day_advice_used") is not False:
        raise ValueError("formal portfolio ledger cannot use same-day advice")


def _validate_temporal_state(
    *,
    input_state: CausalPortfolioState,
    output_state: CausalPortfolioState,
    decision_day: str,
    calendar_positions: Mapping[str, int],
) -> None:
    decision_value = _parse_date(
        decision_day,
        field_name="transition.decision_date",
    )
    output_value = _parse_date(
        output_state.as_of_date,
        field_name="output_state.as_of_date",
    )
    input_value = _parse_date(
        input_state.as_of_date,
        field_name="input_state.as_of_date",
    )
    if output_value != decision_value:
        raise ValueError("formal portfolio ledger output state is not decision-day state")
    if calendar_positions:
        index = calendar_positions.get(decision_day)
        if index is None or index == 0:
            raise ValueError(
                f"formal portfolio ledger has no provable T-1 session: {decision_day}"
            )
        expected = sorted(calendar_positions, key=calendar_positions.__getitem__)[index - 1]
        if input_state.as_of_date != expected:
            raise ValueError(
                f"formal portfolio ledger input state is not T-1: {decision_day}"
            )
    elif input_value >= decision_value:
        raise ValueError("formal portfolio ledger input state is not before decision day")


def _state_from_json(value: str, *, field_name: str) -> CausalPortfolioState:
    payload = _canonical_object(value, field_name=field_name)
    weights = _mapping(payload.get("weights"), f"{field_name}.weights")
    return CausalPortfolioState(
        as_of_date=_required_text(payload.get("as_of_date"), f"{field_name}.as_of_date"),
        weights=_weights_from_mapping(weights, field_name=f"{field_name}.weights"),
        weekly_turnover_used_bp=_required_nonnegative_int(
            payload.get("weekly_turnover_used_bp"),
            f"{field_name}.weekly_turnover_used_bp",
        ),
        state_hash=_required_sha256(payload.get("state_hash"), f"{field_name}.state_hash"),
    )


def _weights_from_json(value: str, *, field_name: str) -> AllocationWeightContract:
    return _weights_from_mapping(
        _canonical_object(value, field_name=field_name),
        field_name=field_name,
    )


def _weights_from_mapping(
    payload: Mapping[str, object],
    *,
    field_name: str,
) -> AllocationWeightContract:
    raw_positions = payload.get("positions_bp")
    if not isinstance(raw_positions, list):
        raise TypeError(f"{field_name}.positions_bp must be an array")
    positions: list[tuple[str, int]] = []
    for index, item in enumerate(raw_positions):
        if not isinstance(item, list) or len(item) != 2:
            raise TypeError(f"{field_name}.positions_bp[{index}] must be a pair")
        symbol = _required_text(item[0], f"{field_name}.positions_bp[{index}].symbol")
        weight = _required_nonnegative_int(
            item[1],
            f"{field_name}.positions_bp[{index}].weight",
        )
        if weight <= 0:
            raise ValueError(f"{field_name}.positions_bp weights must be positive")
        positions.append((symbol, weight))
    if positions != sorted(positions):
        raise ValueError(f"{field_name}.positions_bp must be sorted")
    return AllocationWeightContract(
        positions_bp=tuple(positions),
        cash_bp=_required_nonnegative_int(payload.get("cash_bp"), f"{field_name}.cash_bp"),
    )


def _weight_payload(weights: AllocationWeightContract) -> dict[str, object]:
    return {
        "positions_bp": [[symbol, value] for symbol, value in weights.positions_bp],
        "cash_bp": weights.cash_bp,
    }


def _canonical_object(value: str, *, field_name: str) -> Mapping[str, object]:
    try:
        parsed = json.loads(value)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{field_name} must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise TypeError(f"{field_name} must be an object")
    if _canonical_json(parsed) != value:
        raise ValueError(f"{field_name} must be canonical JSON")
    return parsed


def _calendar_positions(calendar: Sequence[str] | None) -> dict[str, int]:
    if calendar is None:
        return {}
    values = _date_sequence(list(calendar), field_name="calendar")
    return {value: index for index, value in enumerate(values)}


def _date_sequence(value: object, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TypeError(f"{field_name} must be an array")
    result: list[str] = []
    for item in value:
        text = _required_text(item, field_name)
        _parse_date(text, field_name=field_name)
        result.append(text[:10])
    if result != sorted(set(result)):
        raise ValueError(f"{field_name} must be unique and sorted")
    return tuple(result)


def _parse_date(value: str, *, field_name: str) -> date:
    try:
        return date.fromisoformat(value[:10])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an ISO date") from exc


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} must be non-empty text")
    return value


def _required_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be integer")
    return value


def _required_nonnegative_int(value: object, field_name: str) -> int:
    result = _required_int(value, field_name)
    if result < 0:
        raise ValueError(f"{field_name} must be nonnegative")
    return result


def _required_sha256(value: object, field_name: str) -> str:
    result = _required_text(value, field_name)
    digest = result[7:] if result.startswith(_SHA256_PREFIX) else ""
    if len(digest) != 64 or any(item not in "0123456789abcdef" for item in digest):
        raise ValueError(f"{field_name} must be lowercase sha256")
    return result


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("formal portfolio ledger manifest must be an object")
    return value


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be an object")
    return value


def _payload_hash(value: object) -> str:
    return _SHA256_PREFIX + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return _SHA256_PREFIX + digest.hexdigest()
