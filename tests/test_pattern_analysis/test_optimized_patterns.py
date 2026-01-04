#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
測試優化後的圖形模式識別方法

本腳本用於測試優化後的圖形模式識別方法，包括：
1. 楔形模式識別
2. 三角形模式識別
3. 圓底/圓頂模式識別

測試腳本會計算各個模式的識別數量、準確率和收益率，並生成比較報告和可視化圖表。
"""

import os
import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime

# 添加項目根目錄到系統路徑，以便正確導入模塊
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_module.data_loader import DataLoader
from analysis_module.pattern_analyzer import PatternAnalyzer
from analysis_module.technical_analyzer import TechnicalAnalyzer

# 設置基礎路徑
BASE_DIR = "D:/Min/Python/Project/FA_Data"

# 設置測試數據路徑
TEST_DATA_PATH = r"D:\Min\Python\Project\FA_Data\test_data"
# 設置測試結果路徑
TEST_RESULTS_PATH = r"D:\Min\Python\Project\FA_Data\test_data"

# 確保測試數據和結果目錄存在
os.makedirs(TEST_DATA_PATH, exist_ok=True)
os.makedirs(TEST_RESULTS_PATH, exist_ok=True)

# 生成測試結果目錄
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
test_results_dir = os.path.join(TEST_RESULTS_PATH, f"optimized_patterns_{timestamp}")
os.makedirs(test_results_dir, exist_ok=True)

def setup_output_dir():
    """設置輸出目錄"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = f"test_results/optimized_patterns_{timestamp}"
    os.makedirs(output_dir, exist_ok=True)
    return output_dir

def load_test_data():
    """載入測試數據"""
    print("載入測試數據...")
    data_loader = DataLoader()
    
    # 嘗試載入市場指數數據，按優先順序嘗試不同的數據源
    data_files = [
        # 首先嘗試從 BASE_DIR 加載市場指數數據
        os.path.join(BASE_DIR, "meta_data", "market_index.csv"),
        # 然後嘗試加載產業指數數據
        os.path.join(BASE_DIR, "meta_data", "industry_index.csv"),
        # 然後嘗試加載個股交易數據
        os.path.join(BASE_DIR, "meta_data", "stock_data_whole.csv"),
        # 然後嘗試加載整合數據
        os.path.join(BASE_DIR, "meta_data", "all_stocks_data.csv"),
        # 如果 BASE_DIR 的數據都不可用，嘗試加載本地測試數據
        "test_data/SSE_daily.csv",
        "test_data/SP500_daily.csv"
    ]
    
    df = None
    for file_path in data_files:
        try:
            print(f"嘗試從路徑 {file_path} 載入數據...")
            df = data_loader.load_from_csv(file_path)
            print(f"成功從 {file_path} 載入數據")
            break  # 如果成功載入，跳出循環
        except Exception as e:
            print(f"讀取 {file_path} 時出錯: {e}")
    
    # 如果所有數據源都不可用，生成模擬數據
    if df is None:
        print("所有數據源都不可用，生成模擬數據...")
        df = generate_mock_data()
        print("成功生成模擬數據")
    
    # 確保數據包含必要的列
    required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
    for col in required_cols:
        if col not in df.columns:
            if col == 'Volume':
                # 如果沒有成交量數據，生成隨機成交量
                print(f"生成隨機{col}數據")
                df['Volume'] = np.random.randint(100000, 10000000, size=len(df))
            else:
                # 檢查是否存在對應的中文列名
                chinese_cols = {
                    'Open': ['開盤價', '開盤', 'Open'],
                    'High': ['最高價', '最高', 'High'],
                    'Low': ['最低價', '最低', 'Low'],
                    'Close': ['收盤價', '收盤', 'Close'],
                    'Volume': ['成交量', '成交股數', 'Volume']
                }
                
                found = False
                for possible_col in chinese_cols[col]:
                    if possible_col in df.columns:
                        print(f"將'{possible_col}'列映射為'{col}'")
                        df[col] = df[possible_col]
                        found = True
                        break
                
                if not found:
                    raise ValueError(f"數據缺少必要的列: {col}")
    
    # 如果索引不是日期格式，嘗試轉換
    if not isinstance(df.index, pd.DatetimeIndex):
        date_col_found = False
        date_cols = ['日期', '時間', 'date', 'time', 'Date', 'Time']
        
        for col in date_cols:
            if col in df.columns:
                print(f"將{col}列設為日期索引")
                df.set_index(col, inplace=True)
                df.index = pd.to_datetime(df.index)
                date_col_found = True
                break
        
        # 如果沒有找到日期列，則使用默認的日期索引
        if not date_col_found:
            print("使用默認日期索引")
            df.index = pd.date_range(start='2020-01-01', periods=len(df), freq='D')
    
    # 確保日期索引是有序的
    df = df.sort_index()
    
    # 打印日期範圍
    if isinstance(df.index, pd.DatetimeIndex):
        print(f"數據日期範圍：{df.index[0]} 至 {df.index[-1]}")
    
    print(f"數據準備完成，共{len(df)}行，包含列：{', '.join(df.columns)}")
    return df

def generate_mock_data(periods=500):
    """生成模擬數據用於測試"""
    np.random.seed(42)  # 設置隨機種子，確保結果可重複
    
    # 生成日期序列
    dates = pd.date_range(start='2020-01-01', periods=periods, freq='D')
    
    # 初始價格
    initial_price = 100.0
    
    # 生成價格序列
    prices = [initial_price]
    for _ in range(1, periods):
        # 隨機變化率，模擬股票價格波動
        change_pct = np.random.normal(0, 0.015)  # 均值為0，標準差為1.5%
        new_price = prices[-1] * (1 + change_pct)
        prices.append(new_price)
    
    prices = np.array(prices)
    
    # 生成其他價格數據
    high_prices = prices * (1 + np.abs(np.random.normal(0, 0.005, periods)))
    low_prices = prices * (1 - np.abs(np.random.normal(0, 0.005, periods)))
    open_prices = np.array([low_prices[i] + (high_prices[i] - low_prices[i]) * np.random.random() for i in range(periods)])
    
    # 確保開高低收價格符合邏輯關係
    for i in range(periods):
        high_prices[i] = max(high_prices[i], open_prices[i], prices[i])
        low_prices[i] = min(low_prices[i], open_prices[i], prices[i])
    
    # 生成成交量數據
    volumes = np.random.randint(100000, 10000000, size=periods)
    
    # 組合成DataFrame
    df = pd.DataFrame({
        'Open': open_prices,
        'High': high_prices,
        'Low': low_prices,
        'Close': prices,
        'Volume': volumes
    }, index=dates)
    
    return df

def add_technical_indicators(df):
    """添加技術指標"""
    print("添加技術指標...")
    ta = TechnicalAnalyzer()
    
    # 使用TechnicalAnalyzer已有的方法添加技術指標
    # 添加動量指標
    df = ta.add_momentum_indicators(df)
    
    # 添加波動性指標
    df = ta.add_volatility_indicators(df)
    
    # 添加趨勢指標
    df = ta.add_trend_indicators(df)
    
    return df

def test_optimized_patterns(df, output_dir):
    """測試優化後的圖形模式識別方法"""
    print("開始測試優化後的圖形模式識別方法...")
    
    # 初始化PatternAnalyzer
    pattern_analyzer = PatternAnalyzer()
    
    # 設置測試的模式列表
    patterns_to_test = [
        ('楔形', lambda df: pattern_analyzer.identify_wedge(df, window=20, threshold=0.15, min_touches=3, min_r_squared=0.5, min_slope=0.002, min_height_ratio=0.02)),
        ('三角形', lambda df: pattern_analyzer.identify_triangle(df, window=15, threshold=0.15, min_points=4, min_r_squared=0.5, min_height_ratio=0.015)),
        ('圓底', lambda df: pattern_analyzer.identify_rounding_bottom(df, window=20, min_width=10, min_curve=0.5, min_r_squared=0.6, min_depth_ratio=0.02)),
        ('圓頂', lambda df: pattern_analyzer.identify_rounding_top(df, window=20, min_width=10, min_curve=0.5, min_r_squared=0.6, min_height_ratio=0.02))
    ]
    
    # 存儲結果
    results = []
    
    # 在測試之前先截取足夠的交易日數據，考慮使用更多數據
    if len(df) > 500:
        print(f"截取最近的500個交易日數據進行測試（原數據長度：{len(df)}）")
        df_test = df.iloc[-500:].copy()
    else:
        df_test = df.copy()
    
    # 保存測試數據供後續使用
    df_test.to_csv(os.path.join(output_dir, "test_data.csv"), encoding='utf-8-sig')
    
    # 測試每種模式
    for pattern_name, identify_func in patterns_to_test:
        print(f"測試{pattern_name}模式識別...")
        
        # 識別模式
        patterns = identify_func(df_test)
        
        # 記錄識別到的模式數量
        pattern_count = len(patterns)
        print(f"  識別到{pattern_count}個{pattern_name}模式")
        
        # 如果識別到模式，則計算準確率和收益率
        if pattern_count > 0:
            # 計算準確率
            accuracy_result = pattern_analyzer.evaluate_pattern_accuracy(df_test, patterns)
            accuracy = accuracy_result.get('accuracy', 0)
            win_rate = accuracy_result.get('win_rate', 0)
            avg_return = accuracy_result.get('avg_return', 0)
            risk_reward = accuracy_result.get('risk_reward_ratio', 0)
            
            print(f"  準確率: {accuracy:.2%}")
            print(f"  勝率: {win_rate:.2%}")
            print(f"  平均收益率: {avg_return:.2%}")
            print(f"  風險回報比: {risk_reward:.2f}")
            
            # 繪製前10個模式用於可視化
            plot_patterns(df_test, patterns[:min(10, pattern_count)], pattern_name, output_dir)
            
            # 將結果添加到結果列表
            results.append({
                'Pattern': pattern_name,
                'Count': pattern_count,
                'Accuracy': accuracy,
                'Win Rate': win_rate,
                'Avg Return': avg_return,
                'Risk/Reward': risk_reward
            })
        else:
            # 如果沒有識別到模式，添加空結果
            results.append({
                'Pattern': pattern_name,
                'Count': 0,
                'Accuracy': 0,
                'Win Rate': 0,
                'Avg Return': 0,
                'Risk/Reward': 0
            })
    
    # 生成結果報告
    generate_report(results, output_dir)
    
    return results

def plot_patterns(df, patterns, pattern_name, output_dir):
    """繪製識別到的模式"""
    print(f"繪製{pattern_name}模式...")
    
    for i, pattern in enumerate(patterns):
        try:
            start_idx = pattern['start_idx']
            end_idx = pattern['end_idx']
            
            # 確保索引在數據範圍內
            if start_idx < 0:
                start_idx = 0
            if end_idx >= len(df):
                end_idx = len(df) - 1
            
            # 獲取模式前後的數據進行繪製
            padding = min(20, start_idx)  # 向前顯示20個交易日或更少
            plot_start = max(0, start_idx - padding)
            plot_end = min(len(df) - 1, end_idx + padding)  # 向後顯示20個交易日或更少
            
            # 截取數據
            plot_data = df.iloc[plot_start:plot_end+1]
            
            # 創建圖形
            fig, ax = plt.subplots(figsize=(12, 6))
            
            # 繪製價格線
            ax.plot(plot_data.index, plot_data['Close'], label='Close Price')
            
            # 標記模式區域
            pattern_data = df.iloc[start_idx:end_idx+1]
            ax.fill_between(pattern_data.index, pattern_data['Low'], pattern_data['High'], alpha=0.3, color='yellow')
            
            # 添加模式類型和方向標籤
            pattern_type = pattern.get('type', pattern_name)
            direction = pattern.get('direction', 'unknown')
            direction_text = '看漲' if direction == 'bullish' else '看跌' if direction == 'bearish' else '未知'
            
            # 在圖表上添加模式信息
            ax.text(0.02, 0.98, f"模式: {pattern_type} ({direction_text})", 
                   transform=ax.transAxes, verticalalignment='top', fontsize=12)
            
            # 設置圖表標題和標籤
            ax.set_title(f"{pattern_name}模式 #{i+1} - {pattern_data.index[0].strftime('%Y-%m-%d')} 至 {pattern_data.index[-1].strftime('%Y-%m-%d')}")
            ax.set_xlabel('日期')
            ax.set_ylabel('價格')
            ax.legend()
            
            # 旋轉日期標籤以避免重疊
            plt.xticks(rotation=45)
            plt.tight_layout()
            
            # 保存圖形
            plt.savefig(os.path.join(output_dir, f"{pattern_name}_pattern_{i+1}.png"))
            plt.close()
            
        except Exception as e:
            print(f"  繪製{pattern_name}模式 #{i+1} 時出錯: {e}")

def generate_report(results, output_dir):
    """生成結果報告"""
    print("生成結果報告...")
    
    # 將結果轉換為DataFrame
    df_results = pd.DataFrame(results)
    
    # 保存結果
    df_results.to_csv(os.path.join(output_dir, "pattern_results.csv"), index=False, encoding='utf-8-sig')
    
    # 生成柱狀圖
    create_bar_charts(df_results, output_dir)
    
    # 生成雷達圖
    create_radar_chart(df_results, output_dir)
    
    # 生成散點圖
    create_scatter_plot(df_results, output_dir)
    
    # 生成文本報告
    create_text_report(df_results, output_dir)

def create_bar_charts(df, output_dir):
    """創建條形圖，比較不同模式的指標"""
    # 要繪製的指標
    metrics = ['Count', 'Accuracy', 'Win Rate', 'Avg Return', 'Risk/Reward']
    
    # 為每個指標創建條形圖
    for metric in metrics:
        plt.figure(figsize=(10, 6))
        ax = sns.barplot(x='Pattern', y=metric, data=df)
        plt.title(f'模式圖形比較 - {metric}')
        plt.xlabel('模式')
        plt.ylabel(metric)
        plt.xticks(rotation=45)
        
        # 添加數值標籤
        for p in ax.patches:
            if metric in ['Accuracy', 'Win Rate', 'Avg Return']:
                # 百分比格式
                value = f'{p.get_height():.1%}'
            elif metric == 'Risk/Reward':
                # 小數格式
                value = f'{p.get_height():.2f}'
            else:
                # 整數格式
                value = f'{int(p.get_height())}'
                
            ax.annotate(value,
                        (p.get_x() + p.get_width() / 2., p.get_height()),
                        ha='center', va='bottom',
                        fontsize=10)
        
        plt.tight_layout()
        # 將斜線替換為下劃線，以便在Windows文件系統中使用
        safe_metric = metric.replace('/', '_')
        plt.savefig(os.path.join(output_dir, f"bar_chart_{safe_metric}.png"))
        plt.close()

def create_radar_chart(df_results, output_dir):
    """創建雷達圖"""
    # 準備數據
    patterns = df_results['Pattern'].tolist()
    
    # 標準化數值以便在雷達圖上顯示
    metrics = ['Accuracy', 'Win Rate', 'Avg Return', 'Risk/Reward']
    df_norm = df_results.copy()
    
    for metric in metrics:
        if df_norm[metric].max() > 0:
            df_norm[metric] = df_norm[metric] / df_norm[metric].max()
    
    # 設置雷達圖
    angles = np.linspace(0, 2*np.pi, len(metrics), endpoint=False).tolist()
    angles += angles[:1]  # 閉合雷達圖
    
    fig, ax = plt.subplots(figsize=(10, 8), subplot_kw=dict(polar=True))
    
    for i, pattern in enumerate(patterns):
        values = df_norm.loc[i, metrics].tolist()
        values += values[:1]  # 閉合雷達圖
        
        ax.plot(angles, values, linewidth=2, label=pattern)
        ax.fill(angles, values, alpha=0.1)
    
    # 設置雷達圖標籤
    ax.set_thetagrids(np.degrees(angles[:-1]), metrics)
    
    # 添加圖例
    ax.legend(loc='upper right', bbox_to_anchor=(0.1, 0.1))
    
    plt.title('圖形模式性能雷達圖')
    plt.tight_layout()
    
    # 保存雷達圖
    plt.savefig(os.path.join(output_dir, "radar_chart.png"))
    plt.close()

def create_scatter_plot(df_results, output_dir):
    """創建散點圖"""
    plt.figure(figsize=(10, 8))
    
    # 繪製散點圖，顯示準確率vs平均收益率，點的大小表示模式數量
    scatter = plt.scatter(
        df_results['Win Rate'], 
        df_results['Avg Return'], 
        s=df_results['Count'] * 5, 
        c=df_results.index, 
        cmap='viridis', 
        alpha=0.7
    )
    
    # 添加模式標籤
    for i, txt in enumerate(df_results['Pattern']):
        plt.annotate(txt, (df_results['Win Rate'].iloc[i], df_results['Avg Return'].iloc[i]),
                     xytext=(5, 5), textcoords='offset points')
    
    # 設置標題和標籤
    plt.title('圖形模式性能散點圖')
    plt.xlabel('勝率')
    plt.ylabel('平均收益率')
    
    # 添加參考線
    plt.axvline(x=0.5, color='r', linestyle='--', alpha=0.3)
    plt.axhline(y=0, color='r', linestyle='--', alpha=0.3)
    
    # 設置格式
    plt.grid(True, alpha=0.3)
    plt.colorbar(scatter, label='模式索引')
    
    plt.tight_layout()
    
    # 保存散點圖
    plt.savefig(os.path.join(output_dir, "scatter_plot.png"))
    plt.close()

def create_text_report(df_results, output_dir):
    """創建文本報告"""
    report_path = os.path.join(output_dir, "pattern_report.txt")
    
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("# 圖形模式識別優化測試報告\n\n")
        f.write(f"生成時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        f.write("## 摘要\n\n")
        
        # 計算總模式數
        total_patterns = df_results['Count'].sum()
        f.write(f"總計識別出 {int(total_patterns)} 個圖形模式\n\n")
        
        # 找出最準確的模式
        if df_results['Accuracy'].max() > 0:
            best_accuracy_idx = df_results['Accuracy'].idxmax()
            f.write(f"最高準確率: {df_results['Pattern'].iloc[best_accuracy_idx]} - {df_results['Accuracy'].iloc[best_accuracy_idx]:.2%}\n")
        
        # 找出勝率最高的模式
        if df_results['Win Rate'].max() > 0:
            best_win_rate_idx = df_results['Win Rate'].idxmax()
            f.write(f"最高勝率: {df_results['Pattern'].iloc[best_win_rate_idx]} - {df_results['Win Rate'].iloc[best_win_rate_idx]:.2%}\n")
        
        # 找出平均收益率最高的模式
        if df_results['Avg Return'].max() > 0:
            best_return_idx = df_results['Avg Return'].idxmax()
            f.write(f"最高平均收益率: {df_results['Pattern'].iloc[best_return_idx]} - {df_results['Avg Return'].iloc[best_return_idx]:.2%}\n")
        
        # 找出風險回報比最高的模式
        if df_results['Risk/Reward'].max() > 0:
            best_risk_reward_idx = df_results['Risk/Reward'].idxmax()
            f.write(f"最高風險回報比: {df_results['Pattern'].iloc[best_risk_reward_idx]} - {df_results['Risk/Reward'].iloc[best_risk_reward_idx]:.2f}\n\n")
        
        f.write("## 詳細結果\n\n")
        
        # 為每個模式寫入詳細結果
        for i, row in df_results.iterrows():
            f.write(f"### {row['Pattern']}\n\n")
            f.write(f"識別數量: {int(row['Count'])}\n")
            f.write(f"準確率: {row['Accuracy']:.2%}\n")
            f.write(f"勝率: {row['Win Rate']:.2%}\n")
            f.write(f"平均收益率: {row['Avg Return']:.2%}\n")
            f.write(f"風險回報比: {row['Risk/Reward']:.2f}\n\n")
        
        f.write("## 模式比較和建議\n\n")
        
        # 根據綜合評分對模式進行排序
        df_results['Score'] = (
            df_results['Accuracy'] * 0.25 +
            df_results['Win Rate'] * 0.35 +
            df_results['Avg Return'] * 0.25 +
            df_results['Risk/Reward'] / df_results['Risk/Reward'].max() * 0.15  # 標準化風險回報比
        )
        
        # 只考慮有識別結果的模式
        df_valid = df_results[df_results['Count'] > 0].copy()
        
        if not df_valid.empty:
            df_valid = df_valid.sort_values('Score', ascending=False)
            
            f.write("模式綜合評分 (從高到低):\n")
            for i, row in df_valid.iterrows():
                f.write(f"- {row['Pattern']}: {row['Score']:.4f}\n")
            
            f.write("\n建議:\n")
            
            # 提供建議
            if len(df_valid) > 0:
                top_pattern = df_valid.iloc[0]['Pattern']
                f.write(f"1. {top_pattern}模式顯示最佳綜合表現，建議優先考慮此類信號。\n")
            
            if len(df_valid) > 1:
                second_pattern = df_valid.iloc[1]['Pattern']
                f.write(f"2. {second_pattern}模式也表現良好，可作為補充參考。\n")
            
            # 如果有表現較差的模式，給出改進建議
            if len(df_valid) > 2:
                worst_pattern = df_valid.iloc[-1]['Pattern']
                f.write(f"3. {worst_pattern}模式表現相對較差，建議調整參數或與其他指標結合使用以提高準確性。\n")
        else:
            f.write("沒有足夠的有效模式進行比較。建議調整參數或使用更多數據。\n")
        
        f.write("\n## 結論\n\n")
        
        if total_patterns > 0:
            f.write("本次測試顯示，優化後的圖形模式識別方法能夠有效識別市場中的各種圖形模式。")
            
            # 如果有高準確率的模式
            if df_results['Accuracy'].max() > 0.6:
                high_acc_patterns = df_results[df_results['Accuracy'] > 0.6]['Pattern'].tolist()
                if high_acc_patterns:
                    f.write(f" 特別是{', '.join(high_acc_patterns)}等模式表現出較高的準確率。")
            
            f.write(" 建議在實際交易中結合多種技術分析工具，不要僅依賴單一圖形模式。\n")
        else:
            f.write("本次測試中未能識別出足夠的圖形模式，建議使用更多的歷史數據或調整識別參數。\n")
    
    print(f"報告已保存至: {report_path}")

def main():
    # 設置輸出目錄
    output_dir = setup_output_dir()
    print(f"測試結果將保存在: {output_dir}")
    
    try:
        # 載入測試數據
        df = load_test_data()
        
        # 添加技術指標
        df = add_technical_indicators(df)
        
        # 測試優化後的圖形模式識別方法
        results = test_optimized_patterns(df, output_dir)
        
        print(f"測試完成！結果保存在: {output_dir}")
        
    except Exception as e:
        print(f"測試過程中出錯: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main() 