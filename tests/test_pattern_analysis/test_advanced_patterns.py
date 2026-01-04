import os
import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime

# 添加專案根目錄到系統路徑
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 導入模組
from analysis_module.pattern_analyzer import PatternAnalyzer
from data_module.data_loader import DataLoader
from data_module.data_processor import DataProcessor

def test_advanced_patterns():
    """測試進階圖形模式識別功能"""
    print("開始測試進階圖形模式識別功能...")
    
    # 設置數據來源路徑
    data_source_path = r"D:\Min\Python\Project\FA_Data\technical_analysis"
    # 設置測試數據輸出路徑
    test_data_path = r"D:\Min\Python\Project\FA_Data\test_data"
    stock_dir = os.path.join(test_data_path, ticker)
    os.makedirs(stock_dir, exist_ok=True)
    
    # 設置中文字體
    plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'SimHei', 'Arial Unicode MS']
    plt.rcParams['axes.unicode_minus'] = False
    
    # 初始化數據加載器和圖形模式分析器
    data_loader = DataLoader()
    data_processor = DataProcessor()
    pattern_analyzer = PatternAnalyzer()
    
    # 加載測試數據
    ticker = "2330"  # 台積電
    source_csv_path = os.path.join(data_source_path, f"{ticker}_indicators.csv")
    processed_csv_path = os.path.join(stock_dir, f"{ticker}_processed.csv")
    
    # 檢查源數據文件是否存在
    if not os.path.exists(source_csv_path):
        print(f"找不到源數據文件 {source_csv_path}")
        return
    
    # 檢查處理後的數據文件是否存在，如果不存在則從源數據文件加載並處理
    if not os.path.exists(processed_csv_path):
        print(f"處理後的數據文件不存在，從源數據文件加載並處理...")
        df = data_loader.load_from_csv(source_csv_path)
        df = data_processor.clean_data(df)
        df = data_processor.add_basic_features(df)
        data_loader.save_to_csv(df, ticker, test_data_path, suffix="_processed")
    else:
        print(f"從處理後的數據文件加載數據...")
        df = data_loader.load_from_csv(processed_csv_path)
    
    print(f"成功加載數據，共 {len(df)} 筆記錄")
    
    # 測試V形反轉識別
    test_v_reversal(df, ticker, pattern_analyzer, stock_dir)
    
    # 測試圓頂/圓底識別
    test_rounding_patterns(df, ticker, pattern_analyzer, stock_dir)
    
    # 測試矩形識別
    test_rectangle_patterns(df, ticker, pattern_analyzer, stock_dir)
    
    # 測試楔形識別
    test_wedge_patterns(df, ticker, pattern_analyzer, stock_dir)
    
    # 測試所有形態的橫向比較
    test_pattern_comparison(df, ticker, pattern_analyzer, stock_dir)
    
    print("進階圖形模式測試完成")

def test_v_reversal(df, ticker, pattern_analyzer, test_data_path):
    """測試V形反轉識別功能"""
    print("\n測試V形反轉識別...")
    
    try:
        # 識別V形反轉
        v_reversal_positions = pattern_analyzer.identify_v_reversal(df)
        
        if len(v_reversal_positions) > 0:
            print(f"識別出 {len(v_reversal_positions)} 個V形反轉")
            
            # 繪製V形反轉
            pattern_analyzer.plot_pattern(df, v_reversal_positions, "V形反轉")
            plt.savefig(os.path.join(test_data_path, f"{ticker}_v_reversal.png"))
            plt.close()
            
            # 預測V形反轉
            pattern_analyzer.predict_from_pattern(df, v_reversal_positions, "V形反轉")
            plt.savefig(os.path.join(test_data_path, f"{ticker}_v_reversal_forecast.png"))
            plt.close()
            
            # 評估V形反轉準確性
            accuracy = pattern_analyzer.evaluate_pattern_accuracy(df, "V形反轉", v_reversal_positions)
            if accuracy:
                print(f"V形反轉預測準確率: {accuracy['direction_accuracy']:.2f}")
        else:
            print("未識別出V形反轉")
    except Exception as e:
        print(f"測試V形反轉時出錯: {e}")
        import traceback
        traceback.print_exc()

def test_rounding_patterns(df, ticker, pattern_analyzer, test_data_path):
    """測試圓頂/圓底識別功能"""
    print("\n測試圓頂/圓底識別...")
    
    try:
        # 識別圓頂
        rounding_top_positions = pattern_analyzer.identify_rounding_top(df)
        
        if len(rounding_top_positions) > 0:
            print(f"識別出 {len(rounding_top_positions)} 個圓頂形態")
            
            # 繪製圓頂
            pattern_analyzer.plot_pattern(df, rounding_top_positions, "圓頂")
            plt.savefig(os.path.join(test_data_path, f"{ticker}_rounding_top.png"))
            plt.close()
            
            # 預測圓頂
            pattern_analyzer.predict_from_pattern(df, rounding_top_positions, "圓頂")
            plt.savefig(os.path.join(test_data_path, f"{ticker}_rounding_top_forecast.png"))
            plt.close()
            
            # 評估圓頂準確性
            accuracy = pattern_analyzer.evaluate_pattern_accuracy(df, "圓頂", rounding_top_positions)
            if accuracy:
                print(f"圓頂預測準確率: {accuracy['direction_accuracy']:.2f}")
        else:
            print("未識別出圓頂形態")
        
        # 識別圓底
        rounding_bottom_positions = pattern_analyzer.identify_rounding_bottom(df)
        
        if len(rounding_bottom_positions) > 0:
            print(f"識別出 {len(rounding_bottom_positions)} 個圓底形態")
            
            # 繪製圓底
            pattern_analyzer.plot_pattern(df, rounding_bottom_positions, "圓底")
            plt.savefig(os.path.join(test_data_path, f"{ticker}_rounding_bottom.png"))
            plt.close()
            
            # 預測圓底
            pattern_analyzer.predict_from_pattern(df, rounding_bottom_positions, "圓底")
            plt.savefig(os.path.join(test_data_path, f"{ticker}_rounding_bottom_forecast.png"))
            plt.close()
            
            # 評估圓底準確性
            accuracy = pattern_analyzer.evaluate_pattern_accuracy(df, "圓底", rounding_bottom_positions)
            if accuracy:
                print(f"圓底預測準確率: {accuracy['direction_accuracy']:.2f}")
        else:
            print("未識別出圓底形態")
    except Exception as e:
        print(f"測試圓頂/圓底時出錯: {e}")
        import traceback
        traceback.print_exc()

def test_rectangle_patterns(df, ticker, pattern_analyzer, test_data_path):
    """測試矩形識別功能"""
    print("\n測試矩形識別...")
    
    try:
        # 識別矩形
        rectangle_positions = pattern_analyzer.identify_rectangle(df)
        
        if len(rectangle_positions) > 0:
            print(f"識別出 {len(rectangle_positions)} 個矩形形態")
            
            # 繪製矩形
            pattern_analyzer.plot_pattern(df, rectangle_positions, "矩形")
            plt.savefig(os.path.join(test_data_path, f"{ticker}_rectangle.png"))
            plt.close()
            
            # 預測矩形
            pattern_analyzer.predict_from_pattern(df, rectangle_positions, "矩形")
            plt.savefig(os.path.join(test_data_path, f"{ticker}_rectangle_forecast.png"))
            plt.close()
            
            # 評估矩形準確性
            accuracy = pattern_analyzer.evaluate_pattern_accuracy(df, "矩形", rectangle_positions)
            if accuracy:
                print(f"矩形預測準確率: {accuracy['direction_accuracy']:.2f}")
            
            # 分析矩形類型分布
            rectangle_types = [pos['type'] for pos in rectangle_positions if 'type' in pos]
            if rectangle_types:
                plt.figure(figsize=(8, 6))
                plt.pie([rectangle_types.count(t) for t in set(rectangle_types)], 
                       labels=list(set(rectangle_types)), 
                       autopct='%1.1f%%')
                plt.title(f"{ticker} 矩形類型分布")
                plt.savefig(os.path.join(test_data_path, f"{ticker}_rectangle_distribution.png"))
                plt.close()
        else:
            print("未識別出矩形形態")
    except Exception as e:
        print(f"測試矩形時出錯: {e}")
        import traceback
        traceback.print_exc()

def test_wedge_patterns(df, ticker, pattern_analyzer, test_data_path):
    """測試楔形識別功能"""
    print("\n測試楔形識別...")
    
    try:
        # 識別楔形
        wedge_positions = pattern_analyzer.identify_wedge(df)
        
        if len(wedge_positions) > 0:
            print(f"識別出 {len(wedge_positions)} 個楔形形態")
            
            # 繪製楔形
            pattern_analyzer.plot_pattern(df, wedge_positions, "楔形")
            plt.savefig(os.path.join(test_data_path, f"{ticker}_wedge.png"))
            plt.close()
            
            # 預測楔形
            pattern_analyzer.predict_from_pattern(df, wedge_positions, "楔形")
            plt.savefig(os.path.join(test_data_path, f"{ticker}_wedge_forecast.png"))
            plt.close()
            
            # 評估楔形準確性
            accuracy = pattern_analyzer.evaluate_pattern_accuracy(df, "楔形", wedge_positions)
            if accuracy:
                print(f"楔形預測準確率: {accuracy['direction_accuracy']:.2f}")
            
            # 分析楔形類型分布
            wedge_types = [pos['type'] for pos in wedge_positions if 'type' in pos]
            if wedge_types:
                plt.figure(figsize=(8, 6))
                plt.pie([wedge_types.count(t) for t in set(wedge_types)], 
                       labels=list(set(wedge_types)), 
                       autopct='%1.1f%%')
                plt.title(f"{ticker} 楔形類型分布")
                plt.savefig(os.path.join(test_data_path, f"{ticker}_wedge_distribution.png"))
                plt.close()
        else:
            print("未識別出楔形形態")
    except Exception as e:
        print(f"測試楔形時出錯: {e}")
        import traceback
        traceback.print_exc()

def test_pattern_comparison(df, ticker, pattern_analyzer, test_data_path):
    """測試圖形模式橫向比較功能"""
    print("\n測試圖形模式橫向比較...")
    
    try:
        # 定義要比較的所有形態
        all_patterns = [
            'W底', '頭肩頂', '頭肩底', '雙頂', '雙底', '三角形', '旗形',
            'V形反轉', '圓頂', '圓底', '矩形', '楔形'
        ]
        
        # 存儲各形態的評估結果
        pattern_results = {}
        
        # 評估每種形態
        for pattern in all_patterns:
            try:
                # 識別形態
                positions = pattern_analyzer.identify_pattern(df, pattern)
                
                if len(positions) > 0:
                    # 評估準確性
                    accuracy = pattern_analyzer.evaluate_pattern_accuracy(df, pattern, positions)
                    
                    # 計算平均收益率
                    returns = []
                    for pos in positions:
                        if isinstance(pos, dict) and 'forecast_return' in pos:
                            returns.append(pos['forecast_return'])
                    
                    avg_return = np.mean(returns) if returns else 0
                    
                    # 計算風險回報比
                    risk_reward = 0
                    if returns:
                        # 判斷是否為看跌形態
                        is_bearish = pattern in ['頭肩頂', '雙頂', '圓頂'] or \
                                    (pattern == '三角形' and any(pos.get('type') == 'descending' for pos in positions if isinstance(pos, dict))) or \
                                    (pattern == '旗形' and any(pos.get('direction') == 'bearish' for pos in positions if isinstance(pos, dict))) or \
                                    (pattern == '楔形' and any(pos.get('direction') == 'bearish' for pos in positions if isinstance(pos, dict)))
                        
                        if is_bearish:
                            # 對於看跌形態，負收益率是"收益"，正收益率是"損失"
                            gains = [abs(r) for r in returns if r < 0]  # 負收益率的絕對值作為收益
                            losses = [r for r in returns if r > 0]  # 正收益率作為損失
                        else:
                            # 對於看漲形態，正收益率是"收益"，負收益率是"損失"
                            gains = [r for r in returns if r > 0]
                            losses = [abs(r) for r in returns if r < 0]
                        
                        avg_gain = np.mean(gains) if gains else 0
                        avg_loss = np.mean(losses) if losses else 1  # 避免除以零
                        risk_reward = avg_gain / avg_loss if avg_loss > 0 else 0
                    
                    # 存儲結果
                    pattern_results[pattern] = {
                        'count': len(positions),
                        'accuracy': accuracy['direction_accuracy'] if accuracy else 0,
                        'avg_return': avg_return,
                        'risk_reward': risk_reward
                    }
                    
                    print(f"{pattern}: 識別 {len(positions)} 個, 準確率 {pattern_results[pattern]['accuracy']:.2f}, 平均收益 {avg_return:.2f}%, 風險回報比 {risk_reward:.2f}")
                else:
                    print(f"{pattern}: 未識別出形態")
                    pattern_results[pattern] = {
                        'count': 0,
                        'accuracy': 0,
                        'avg_return': 0,
                        'risk_reward': 0
                    }
            except Exception as e:
                print(f"評估 {pattern} 時出錯: {e}")
                pattern_results[pattern] = {
                    'count': 0,
                    'accuracy': 0,
                    'avg_return': 0,
                    'risk_reward': 0
                }
        
        # 生成比較圖表
        
        # 1. 各形態勝率比較柱狀圖
        plt.figure(figsize=(12, 6))
        patterns = [p for p in pattern_results.keys() if pattern_results[p]['count'] > 0]
        if patterns:
            accuracies = [pattern_results[p]['accuracy'] for p in patterns]
            
            plt.bar(patterns, accuracies)
            plt.title(f"{ticker} 各圖形模式勝率比較")
            plt.xlabel("圖形模式")
            plt.ylabel("勝率")
            plt.xticks(rotation=45)
            plt.tight_layout()
            plt.savefig(os.path.join(test_data_path, f"{ticker}_pattern_accuracy_comparison.png"))
            plt.close()
        
        # 2. 各形態平均收益率比較柱狀圖
        plt.figure(figsize=(12, 6))
        if patterns:
            returns = [pattern_results[p]['avg_return'] for p in patterns]
            
            plt.bar(patterns, returns)
            plt.title(f"{ticker} 各圖形模式平均收益率比較")
            plt.xlabel("圖形模式")
            plt.ylabel("平均收益率 (%)")
            plt.xticks(rotation=45)
            plt.tight_layout()
            plt.savefig(os.path.join(test_data_path, f"{ticker}_pattern_return_comparison.png"))
            plt.close()
        
        # 3. 風險回報比雷達圖
        if len(patterns) >= 3:  # 雷達圖至少需要3個點
            plt.figure(figsize=(10, 8))
            risk_rewards = [pattern_results[p]['risk_reward'] for p in patterns]
            
            # 雷達圖設置
            angles = np.linspace(0, 2*np.pi, len(patterns), endpoint=False).tolist()
            risk_rewards.append(risk_rewards[0])  # 閉合雷達圖
            angles.append(angles[0])  # 閉合雷達圖
            patterns_radar = patterns + [patterns[0]]  # 閉合雷達圖
            
            ax = plt.subplot(111, polar=True)
            ax.plot(angles, risk_rewards)
            ax.fill(angles, risk_rewards, alpha=0.25)
            ax.set_thetagrids(np.degrees(angles[:-1]), patterns)
            plt.title(f"{ticker} 各圖形模式風險回報比")
            plt.tight_layout()
            plt.savefig(os.path.join(test_data_path, f"{ticker}_pattern_risk_reward_radar.png"))
            plt.close()
        
        # 4. 形態識別頻率與準確性散點圖
        plt.figure(figsize=(10, 8))
        if patterns:
            counts = [pattern_results[p]['count'] for p in patterns]
            accuracies = [pattern_results[p]['accuracy'] for p in patterns]
            
            plt.scatter(counts, accuracies)
            for i, p in enumerate(patterns):
                plt.annotate(p, (counts[i], accuracies[i]))
            
            plt.title(f"{ticker} 圖形模式識別頻率與準確性關係")
            plt.xlabel("識別頻率")
            plt.ylabel("準確性")
            plt.grid(True)
            plt.tight_layout()
            plt.savefig(os.path.join(test_data_path, f"{ticker}_pattern_frequency_accuracy.png"))
            plt.close()
        
        # 5. 綜合評分圖表（綜合考慮頻率、準確性和收益率）
        plt.figure(figsize=(12, 6))
        if patterns:
            # 計算綜合評分 (簡單加權平均)
            scores = []
            for p in patterns:
                # 標準化各指標
                max_count = max([pattern_results[p2]['count'] for p2 in patterns]) if patterns else 1
                count_norm = pattern_results[p]['count'] / max_count if max_count > 0 else 0
                accuracy_norm = pattern_results[p]['accuracy']
                
                min_return = min([pattern_results[p2]['avg_return'] for p2 in patterns]) if patterns else 0
                max_return = max([pattern_results[p2]['avg_return'] for p2 in patterns]) if patterns else 1
                return_range = max_return - min_return
                return_norm = (pattern_results[p]['avg_return'] - min_return) / return_range if return_range > 0 else 0
                
                # 加權平均
                score = 0.2 * count_norm + 0.4 * accuracy_norm + 0.4 * return_norm
                scores.append(score)
            
            plt.bar(patterns, scores)
            plt.title(f"{ticker} 各圖形模式綜合評分")
            plt.xlabel("圖形模式")
            plt.ylabel("綜合評分")
            plt.xticks(rotation=45)
            plt.tight_layout()
            plt.savefig(os.path.join(test_data_path, f"{ticker}_pattern_overall_score.png"))
            plt.close()
        
        # 生成比較報告
        report_path = os.path.join(test_data_path, f"{ticker}_pattern_comparison_report.txt")
        with open(report_path, 'w', encoding='utf-8-sig') as f:
            f.write(f"# {ticker} 圖形模式比較分析報告\n\n")
            f.write(f"分析日期: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            f.write("## 各圖形模式表現統計\n\n")
            f.write("| 圖形模式 | 識別次數 | 準確率 | 平均收益率 (%) | 風險回報比 | 綜合評分 |\n")
            f.write("|----------|----------|--------|----------------|------------|----------|\n")
            
            for i, p in enumerate(patterns):
                score_index = patterns.index(p) if p in patterns else -1
                score = scores[score_index] if score_index >= 0 and score_index < len(scores) else 0
                f.write(f"| {p} | {pattern_results[p]['count']} | {pattern_results[p]['accuracy']:.2f} | {pattern_results[p]['avg_return']:.2f} | {pattern_results[p]['risk_reward']:.2f} | {score:.2f} |\n")
            
            f.write("\n## 表現最佳的圖形模式\n\n")
            
            # 按綜合評分排序
            if patterns and scores:
                sorted_patterns = [p for _, p in sorted(zip(scores, patterns), reverse=True)]
                
                if sorted_patterns:
                    best_pattern = sorted_patterns[0]
                    f.write(f"### 1. {best_pattern}\n")
                    f.write(f"- 識別次數: {pattern_results[best_pattern]['count']}\n")
                    f.write(f"- 準確率: {pattern_results[best_pattern]['accuracy']:.2f}\n")
                    f.write(f"- 平均收益率: {pattern_results[best_pattern]['avg_return']:.2f}%\n")
                    f.write(f"- 風險回報比: {pattern_results[best_pattern]['risk_reward']:.2f}\n")
                    f.write(f"- 綜合評分: {scores[sorted_patterns.index(best_pattern)]:.2f}\n\n")
                    
                    if len(sorted_patterns) > 1:
                        second_best = sorted_patterns[1]
                        f.write(f"### 2. {second_best}\n")
                        f.write(f"- 識別次數: {pattern_results[second_best]['count']}\n")
                        f.write(f"- 準確率: {pattern_results[second_best]['accuracy']:.2f}\n")
                        f.write(f"- 平均收益率: {pattern_results[second_best]['avg_return']:.2f}%\n")
                        f.write(f"- 風險回報比: {pattern_results[second_best]['risk_reward']:.2f}\n")
                        f.write(f"- 綜合評分: {scores[sorted_patterns.index(second_best)]:.2f}\n\n")
                    
                    if len(sorted_patterns) > 2:
                        third_best = sorted_patterns[2]
                        f.write(f"### 3. {third_best}\n")
                        f.write(f"- 識別次數: {pattern_results[third_best]['count']}\n")
                        f.write(f"- 準確率: {pattern_results[third_best]['accuracy']:.2f}\n")
                        f.write(f"- 平均收益率: {pattern_results[third_best]['avg_return']:.2f}%\n")
                        f.write(f"- 風險回報比: {pattern_results[third_best]['risk_reward']:.2f}\n")
                        f.write(f"- 綜合評分: {scores[sorted_patterns.index(third_best)]:.2f}\n\n")
            
            f.write("## 分析結論\n\n")
            
            if patterns and scores and sorted_patterns:
                f.write(f"1. 對於 {ticker}，表現最佳的圖形模式是 {sorted_patterns[0]}，綜合評分為 {scores[sorted_patterns.index(sorted_patterns[0])]:.2f}。\n")
                
                # 按準確率排序
                accuracy_sorted = [p for _, p in sorted([(pattern_results[p]['accuracy'], p) for p in patterns], reverse=True)]
                if accuracy_sorted:
                    f.write(f"2. 準確率最高的圖形模式是 {accuracy_sorted[0]}，準確率為 {pattern_results[accuracy_sorted[0]]['accuracy']:.2f}。\n")
                
                # 按平均收益率排序
                return_sorted = [p for _, p in sorted([(pattern_results[p]['avg_return'], p) for p in patterns], reverse=True)]
                if return_sorted:
                    f.write(f"3. 平均收益率最高的圖形模式是 {return_sorted[0]}，平均收益率為 {pattern_results[return_sorted[0]]['avg_return']:.2f}%。\n")
                
                # 按風險回報比排序
                risk_reward_sorted = [p for _, p in sorted([(pattern_results[p]['risk_reward'], p) for p in patterns], reverse=True)]
                if risk_reward_sorted:
                    f.write(f"4. 風險回報比最高的圖形模式是 {risk_reward_sorted[0]}，風險回報比為 {pattern_results[risk_reward_sorted[0]]['risk_reward']:.2f}。\n\n")
                
                f.write("## 交易建議\n\n")
                
                f.write(f"基於以上分析，建議優先關注以下圖形模式：\n\n")
                for i, p in enumerate(sorted_patterns[:3]):
                    f.write(f"{i+1}. {p}\n")
                
                f.write("\n這些形態在歷史數據中表現較好，可能具有較高的交易價值。建議在實際交易中結合其他技術指標和基本面分析，以提高交易成功率。\n")
        
        print(f"比較報告已保存到 {report_path}")
    except Exception as e:
        print(f"測試圖形模式橫向比較時出錯: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_advanced_patterns() 