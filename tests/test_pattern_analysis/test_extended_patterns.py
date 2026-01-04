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

def test_extended_patterns():
    """測試擴展的圖形模式識別功能"""
    print("開始測試擴展的圖形模式識別功能...")
    
    # 設置數據來源路徑
    data_source_path = r"D:\Min\Python\Project\FA_Data\technical_analysis"
    # 設置測試數據輸出路徑
    test_data_path = r"D:\Min\Python\Project\FA_Data\test_data"
    stock_dir = os.path.join(test_data_path, ticker)
    os.makedirs(stock_dir, exist_ok=True)
    
    # 確保測試數據目錄存在
    if not os.path.exists(test_data_path):
        test_data_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
        if not os.path.exists(test_data_path):
            os.makedirs(test_data_path)
    
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
    if os.path.exists(processed_csv_path):
        print(f"使用已處理的數據文件 {processed_csv_path}")
        df_cleaned = data_loader.load_from_csv(processed_csv_path)
    else:
        print(f"從源數據文件 {source_csv_path} 加載數據並處理")
        df = data_loader.load_from_csv(source_csv_path)
        print(f"成功加載 {ticker} 的數據，共 {len(df)} 行")
        
        # 清理數據
        df_cleaned = data_processor.clean_data(df)
        print(f"清理後的數據，共 {len(df_cleaned)} 行")
        
        # 保存處理後的數據
        data_loader.save_to_csv(df_cleaned, processed_csv_path)
        print(f"處理後的數據已保存至 {processed_csv_path}")
    
    print(f"使用的數據，共 {len(df_cleaned)} 行")
    
    # 用於保存圖表的字典
    chart_dict = {}
    
    # 用於保存識別結果的字典
    pattern_results = {}
    
    # 測試雙頂識別
    print("\n正在識別雙頂形態...")
    double_top_positions = pattern_analyzer.identify_pattern(df_cleaned, '雙頂', window=30, threshold=0.1)
    print(f"找到 {len(double_top_positions)} 個雙頂形態")
    
    # 保存識別結果
    pattern_results['雙頂'] = {
        'positions': double_top_positions,
        'count': len(double_top_positions)
    }
    
    if double_top_positions:
        # 繪製雙頂形態
        print("正在繪製雙頂形態...")
        plt.figure(figsize=(12, 6))
        plt.plot(df_cleaned.index, df_cleaned['收盤價'], label='收盤價')
        
        # 標記識別出的雙頂形態
        for i, (start_idx, end_idx) in enumerate(double_top_positions):
            # 只標記最近的 20 個形態，避免圖表過於擁擠
            if i >= len(double_top_positions) - 20:
                plt.axvspan(df_cleaned.index[start_idx], df_cleaned.index[end_idx], alpha=0.2, color='red')
                # 只在每 5 個形態上添加標籤，避免標籤重疊
                if i % 5 == 0:
                    plt.text(df_cleaned.index[start_idx], df_cleaned['收盤價'].iloc[start_idx], '雙頂', 
                             fontsize=10, color='red')
        
        plt.title(f'{ticker} - 雙頂形態識別 (共 {len(double_top_positions)} 個)')
        plt.legend()
        plt.grid(True)
        
        # 保存圖表
        chart_path = os.path.join(stock_dir, f"{ticker}_double_top.png")
        plt.savefig(chart_path)
        print(f"雙頂形態圖表已保存至 {chart_path}")
        
        # 將圖表對象保存到字典中
        chart_dict['雙頂'] = plt.gcf()
        
        # 根據雙頂形態進行預測
        print("\n正在根據雙頂形態進行預測...")
        # 只使用最後一個雙頂形態進行預測
        last_double_top = [double_top_positions[-1]]
        forecast_df = pattern_analyzer.predict_from_pattern(df_cleaned, last_double_top, '雙頂', forecast_periods=30)
        
        if forecast_df is not None:
            # 繪製預測結果
            plt.figure(figsize=(12, 6))
            plt.plot(df_cleaned.index[-100:], df_cleaned['收盤價'].iloc[-100:], label='歷史收盤價')
            plt.plot(forecast_df.index, forecast_df['收盤價'], label='預測收盤價', linestyle='--', color='red')
            plt.title(f'{ticker} - 基於最近的雙頂形態的價格預測')
            plt.legend()
            plt.grid(True)
            
            # 保存預測圖表
            forecast_chart_path = os.path.join(stock_dir, f"{ticker}_double_top_forecast.png")
            plt.savefig(forecast_chart_path)
            print(f"雙頂形態預測圖表已保存至 {forecast_chart_path}")
            
            # 將預測圖表對象保存到字典中
            chart_dict['雙頂_預測'] = plt.gcf()
        
        # 評估雙頂形態的準確性
        print("\n正在評估雙頂形態的準確性...")
        accuracy_result = pattern_analyzer.evaluate_pattern_accuracy(df_cleaned, '雙頂', window=30, threshold=0.1)
        if accuracy_result:
            print(f"雙頂形態的準確性評估結果:")
            print(f"- 平均均方誤差 (MSE): {accuracy_result['avg_mse']:.4f}")
            print(f"- 平均絕對誤差 (MAE): {accuracy_result['avg_mae']:.4f}")
            print(f"- 方向準確率: {accuracy_result['direction_accuracy']*100:.2f}%")
            
            # 保存準確性評估結果
            pattern_results['雙頂']['accuracy'] = accuracy_result
    
    # 測試雙底識別
    print("\n正在識別雙底形態...")
    double_bottom_positions = pattern_analyzer.identify_pattern(df_cleaned, '雙底', window=30, threshold=0.1)
    print(f"找到 {len(double_bottom_positions)} 個雙底形態")
    
    # 保存識別結果
    pattern_results['雙底'] = {
        'positions': double_bottom_positions,
        'count': len(double_bottom_positions)
    }
    
    if double_bottom_positions:
        # 繪製雙底形態
        print("正在繪製雙底形態...")
        plt.figure(figsize=(12, 6))
        plt.plot(df_cleaned.index, df_cleaned['收盤價'], label='收盤價')
        
        # 標記識別出的雙底形態
        for i, (start_idx, end_idx) in enumerate(double_bottom_positions):
            # 只標記最近的 20 個形態，避免圖表過於擁擠
            if i >= len(double_bottom_positions) - 20:
                plt.axvspan(df_cleaned.index[start_idx], df_cleaned.index[end_idx], alpha=0.2, color='green')
                # 只在每 5 個形態上添加標籤，避免標籤重疊
                if i % 5 == 0:
                    plt.text(df_cleaned.index[start_idx], df_cleaned['收盤價'].iloc[start_idx], '雙底', 
                             fontsize=10, color='green')
        
        plt.title(f'{ticker} - 雙底形態識別 (共 {len(double_bottom_positions)} 個)')
        plt.legend()
        plt.grid(True)
        
        # 保存圖表
        chart_path = os.path.join(stock_dir, f"{ticker}_double_bottom.png")
        plt.savefig(chart_path)
        print(f"雙底形態圖表已保存至 {chart_path}")
        
        # 將圖表對象保存到字典中
        chart_dict['雙底'] = plt.gcf()
        
        # 根據雙底形態進行預測
        print("\n正在根據雙底形態進行預測...")
        # 只使用最後一個雙底形態進行預測
        last_double_bottom = [double_bottom_positions[-1]]
        forecast_df = pattern_analyzer.predict_from_pattern(df_cleaned, last_double_bottom, '雙底', forecast_periods=30)
        
        if forecast_df is not None:
            # 繪製預測結果
            plt.figure(figsize=(12, 6))
            plt.plot(df_cleaned.index[-100:], df_cleaned['收盤價'].iloc[-100:], label='歷史收盤價')
            plt.plot(forecast_df.index, forecast_df['收盤價'], label='預測收盤價', linestyle='--', color='green')
            plt.title(f'{ticker} - 基於最近的雙底形態的價格預測')
            plt.legend()
            plt.grid(True)
            
            # 保存預測圖表
            forecast_chart_path = os.path.join(stock_dir, f"{ticker}_double_bottom_forecast.png")
            plt.savefig(forecast_chart_path)
            print(f"雙底形態預測圖表已保存至 {forecast_chart_path}")
            
            # 將預測圖表對象保存到字典中
            chart_dict['雙底_預測'] = plt.gcf()
        
        # 評估雙底形態的準確性
        print("\n正在評估雙底形態的準確性...")
        accuracy_result = pattern_analyzer.evaluate_pattern_accuracy(df_cleaned, '雙底', window=30, threshold=0.1)
        if accuracy_result:
            print(f"雙底形態的準確性評估結果:")
            print(f"- 平均均方誤差 (MSE): {accuracy_result['avg_mse']:.4f}")
            print(f"- 平均絕對誤差 (MAE): {accuracy_result['avg_mae']:.4f}")
            print(f"- 方向準確率: {accuracy_result['direction_accuracy']*100:.2f}%")
            
            # 保存準確性評估結果
            pattern_results['雙底']['accuracy'] = accuracy_result
    
    # 測試三角形識別
    print("\n正在識別三角形形態...")
    triangle_positions = pattern_analyzer.identify_pattern(df_cleaned, '三角形', window=50, threshold=0.1)
    print(f"找到 {len(triangle_positions)} 個三角形形態")
    
    # 保存識別結果
    pattern_results['三角形'] = {
        'positions': triangle_positions,
        'count': len(triangle_positions)
    }
    
    if triangle_positions:
        # 分析三角形類型分布
        triangle_types = {}
        for _, _, pattern_type in triangle_positions:
            if pattern_type not in triangle_types:
                triangle_types[pattern_type] = 0
            triangle_types[pattern_type] += 1
        
        print("三角形類型分布:")
        for t_type, count in triangle_types.items():
            print(f"- {t_type}三角形: {count} 個 ({count/len(triangle_positions)*100:.2f}%)")
        
        # 保存三角形類型分布
        pattern_results['三角形']['type_distribution'] = triangle_types
        
        # 繪製三角形形態
        print("正在繪製三角形形態...")
        plt.figure(figsize=(12, 6))
        plt.plot(df_cleaned.index, df_cleaned['收盤價'], label='收盤價')
        
        # 標記識別出的三角形形態
        for i, (start_idx, end_idx, pattern_type) in enumerate(triangle_positions):
            # 只標記最近的 20 個形態，避免圖表過於擁擠
            if i >= len(triangle_positions) - 20:
                color = 'blue'
                plt.axvspan(df_cleaned.index[start_idx], df_cleaned.index[end_idx], alpha=0.2, color=color)
                # 只在每 5 個形態上添加標籤，避免標籤重疊
                if i % 5 == 0:
                    plt.text(df_cleaned.index[start_idx], df_cleaned['收盤價'].iloc[start_idx], f'{pattern_type}三角形', 
                             fontsize=10, color=color)
        
        plt.title(f'{ticker} - 三角形形態識別 (共 {len(triangle_positions)} 個)')
        plt.legend()
        plt.grid(True)
        
        # 保存圖表
        chart_path = os.path.join(stock_dir, f"{ticker}_triangle.png")
        plt.savefig(chart_path)
        print(f"三角形形態圖表已保存至 {chart_path}")
        
        # 將圖表對象保存到字典中
        chart_dict['三角形'] = plt.gcf()
        
        # 繪製三角形類型分布餅圖
        plt.figure(figsize=(8, 8))
        plt.pie(triangle_types.values(), labels=[f"{t} ({c})" for t, c in triangle_types.items()], 
                autopct='%1.1f%%', startangle=90)
        plt.axis('equal')
        plt.title(f'{ticker} - 三角形類型分布')
        
        # 保存餅圖
        pie_chart_path = os.path.join(stock_dir, f"{ticker}_triangle_distribution.png")
        plt.savefig(pie_chart_path)
        print(f"三角形類型分布餅圖已保存至 {pie_chart_path}")
        
        # 將餅圖對象保存到字典中
        chart_dict['三角形_分布'] = plt.gcf()
        
        # 根據三角形形態進行預測
        print("\n正在根據三角形形態進行預測...")
        # 只使用最後一個三角形形態進行預測
        last_triangle = [triangle_positions[-1]]
        forecast_df = pattern_analyzer.predict_from_pattern(df_cleaned, last_triangle, '三角形', forecast_periods=30)
        
        if forecast_df is not None:
            # 繪製預測結果
            plt.figure(figsize=(12, 6))
            plt.plot(df_cleaned.index[-100:], df_cleaned['收盤價'].iloc[-100:], label='歷史收盤價')
            plt.plot(forecast_df.index, forecast_df['收盤價'], label='預測收盤價', linestyle='--', color='blue')
            plt.title(f'{ticker} - 基於最近的{last_triangle[0][2]}三角形形態的價格預測')
            plt.legend()
            plt.grid(True)
            
            # 保存預測圖表
            forecast_chart_path = os.path.join(stock_dir, f"{ticker}_triangle_forecast.png")
            plt.savefig(forecast_chart_path)
            print(f"三角形形態預測圖表已保存至 {forecast_chart_path}")
            
            # 將預測圖表對象保存到字典中
            chart_dict['三角形_預測'] = plt.gcf()
    
    # 測試旗形識別
    print("\n正在識別旗形形態...")
    flag_positions = pattern_analyzer.identify_pattern(df_cleaned, '旗形', window=30, threshold=0.1)
    print(f"找到 {len(flag_positions)} 個旗形形態")
    
    # 保存識別結果
    pattern_results['旗形'] = {
        'positions': flag_positions,
        'count': len(flag_positions)
    }
    
    if flag_positions:
        # 分析旗形類型分布
        flag_types = {}
        for _, _, pattern_type in flag_positions:
            if pattern_type not in flag_types:
                flag_types[pattern_type] = 0
            flag_types[pattern_type] += 1
        
        print("旗形類型分布:")
        for f_type, count in flag_types.items():
            print(f"- {f_type}旗形: {count} 個 ({count/len(flag_positions)*100:.2f}%)")
        
        # 保存旗形類型分布
        pattern_results['旗形']['type_distribution'] = flag_types
        
        # 繪製旗形形態
        print("正在繪製旗形形態...")
        plt.figure(figsize=(12, 6))
        plt.plot(df_cleaned.index, df_cleaned['收盤價'], label='收盤價')
        
        # 標記識別出的旗形形態
        for i, (start_idx, end_idx, pattern_type) in enumerate(flag_positions):
            # 只標記最近的 20 個形態，避免圖表過於擁擠
            if i >= len(flag_positions) - 20:
                color = 'purple'
                plt.axvspan(df_cleaned.index[start_idx], df_cleaned.index[end_idx], alpha=0.2, color=color)
                # 只在每 5 個形態上添加標籤，避免標籤重疊
                if i % 5 == 0:
                    plt.text(df_cleaned.index[start_idx], df_cleaned['收盤價'].iloc[start_idx], f'{pattern_type}旗形', 
                             fontsize=10, color=color)
        
        plt.title(f'{ticker} - 旗形形態識別 (共 {len(flag_positions)} 個)')
        plt.legend()
        plt.grid(True)
        
        # 保存圖表
        chart_path = os.path.join(stock_dir, f"{ticker}_flag.png")
        plt.savefig(chart_path)
        print(f"旗形形態圖表已保存至 {chart_path}")
        
        # 將圖表對象保存到字典中
        chart_dict['旗形'] = plt.gcf()
        
        # 繪製旗形類型分布餅圖
        plt.figure(figsize=(8, 8))
        plt.pie(flag_types.values(), labels=[f"{t} ({c})" for t, c in flag_types.items()], 
                autopct='%1.1f%%', startangle=90)
        plt.axis('equal')
        plt.title(f'{ticker} - 旗形類型分布')
        
        # 保存餅圖
        pie_chart_path = os.path.join(stock_dir, f"{ticker}_flag_distribution.png")
        plt.savefig(pie_chart_path)
        print(f"旗形類型分布餅圖已保存至 {pie_chart_path}")
        
        # 將餅圖對象保存到字典中
        chart_dict['旗形_分布'] = plt.gcf()
        
        # 根據旗形形態進行預測
        print("\n正在根據旗形形態進行預測...")
        # 只使用最後一個旗形形態進行預測
        last_flag = [flag_positions[-1]]
        forecast_df = pattern_analyzer.predict_from_pattern(df_cleaned, last_flag, '旗形', forecast_periods=30)
        
        if forecast_df is not None:
            # 繪製預測結果
            plt.figure(figsize=(12, 6))
            plt.plot(df_cleaned.index[-100:], df_cleaned['收盤價'].iloc[-100:], label='歷史收盤價')
            plt.plot(forecast_df.index, forecast_df['收盤價'], label='預測收盤價', linestyle='--', color='purple')
            plt.title(f'{ticker} - 基於最近的{last_flag[0][2]}旗形形態的價格預測')
            plt.legend()
            plt.grid(True)
            
            # 保存預測圖表
            forecast_chart_path = os.path.join(stock_dir, f"{ticker}_flag_forecast.png")
            plt.savefig(forecast_chart_path)
            print(f"旗形形態預測圖表已保存至 {forecast_chart_path}")
            
            # 將預測圖表對象保存到字典中
            chart_dict['旗形_預測'] = plt.gcf()
    
    # 生成綜合分析報告
    print("\n正在生成綜合分析報告...")
    report_path = os.path.join(stock_dir, f"{ticker}_pattern_analysis_report.txt")
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(f"圖形模式分析報告 - {ticker}\n")
        f.write("="*50 + "\n\n")
        
        f.write("1. 識別結果統計\n")
        f.write("-"*50 + "\n")
        for pattern_type, result in pattern_results.items():
            f.write(f"{pattern_type}: {result['count']} 個\n")
        f.write("\n")
        
        # 寫入三角形類型分布
        if 'type_distribution' in pattern_results.get('三角形', {}):
            f.write("2. 三角形類型分布\n")
            f.write("-"*50 + "\n")
            for t_type, count in pattern_results['三角形']['type_distribution'].items():
                f.write(f"{t_type}三角形: {count} 個 ({count/pattern_results['三角形']['count']*100:.2f}%)\n")
            f.write("\n")
        
        # 寫入旗形類型分布
        if 'type_distribution' in pattern_results.get('旗形', {}):
            f.write("3. 旗形類型分布\n")
            f.write("-"*50 + "\n")
            for f_type, count in pattern_results['旗形']['type_distribution'].items():
                f.write(f"{f_type}旗形: {count} 個 ({count/pattern_results['旗形']['count']*100:.2f}%)\n")
            f.write("\n")
        
        # 寫入準確性評估結果
        f.write("4. 準確性評估\n")
        f.write("-"*50 + "\n")
        for pattern_type, result in pattern_results.items():
            if 'accuracy' in result:
                f.write(f"{pattern_type}形態的準確性評估結果:\n")
                f.write(f"- 平均均方誤差 (MSE): {result['accuracy']['avg_mse']:.4f}\n")
                f.write(f"- 平均絕對誤差 (MAE): {result['accuracy']['avg_mae']:.4f}\n")
                f.write(f"- 方向準確率: {result['accuracy']['direction_accuracy']*100:.2f}%\n\n")
        
        # 寫入最近識別的形態
        f.write("5. 最近識別的形態\n")
        f.write("-"*50 + "\n")
        for pattern_type, result in pattern_results.items():
            if result['count'] > 0:
                if pattern_type in ['三角形', '旗形']:
                    last_pattern = result['positions'][-1]
                    start_idx, end_idx, subtype = last_pattern
                    f.write(f"最近的{pattern_type}形態 ({subtype}):\n")
                else:
                    last_pattern = result['positions'][-1]
                    start_idx, end_idx = last_pattern
                    f.write(f"最近的{pattern_type}形態:\n")
                
                # 使用日期索引而不是數字索引
                start_date = df_cleaned.index[start_idx]
                end_date = df_cleaned.index[end_idx]
                
                f.write(f"- 開始日期: {start_date.strftime('%Y-%m-%d')}\n")
                f.write(f"- 結束日期: {end_date.strftime('%Y-%m-%d')}\n")
                f.write(f"- 持續天數: {end_idx - start_idx + 1}\n")
                f.write(f"- 開始價格: {df_cleaned['收盤價'].iloc[start_idx]:.2f}\n")
                f.write(f"- 結束價格: {df_cleaned['收盤價'].iloc[end_idx]:.2f}\n")
                f.write(f"- 價格變化: {df_cleaned['收盤價'].iloc[end_idx] - df_cleaned['收盤價'].iloc[start_idx]:.2f} ({(df_cleaned['收盤價'].iloc[end_idx] / df_cleaned['收盤價'].iloc[start_idx] - 1) * 100:.2f}%)\n\n")
    
    print(f"綜合分析報告已保存至 {report_path}")
    
    # 繪製所有形態的數量比較柱狀圖
    plt.figure(figsize=(10, 6))
    pattern_types = list(pattern_results.keys())
    pattern_counts = [result['count'] for result in pattern_results.values()]
    
    plt.bar(pattern_types, pattern_counts, color=['red', 'green', 'blue', 'purple'])
    plt.title(f'{ticker} - 各種圖形模式數量比較')
    plt.xlabel('圖形模式類型')
    plt.ylabel('識別數量')
    
    # 在柱子上方顯示數量
    for i, count in enumerate(pattern_counts):
        plt.text(i, count + 10, str(count), ha='center')
    
    # 保存柱狀圖
    bar_chart_path = os.path.join(stock_dir, f"{ticker}_pattern_count_comparison.png")
    plt.savefig(bar_chart_path)
    print(f"圖形模式數量比較柱狀圖已保存至 {bar_chart_path}")
    
    # 將柱狀圖對象保存到字典中
    chart_dict['數量比較'] = plt.gcf()
    
    # 保存綜合圖表
    chart_path = os.path.join(stock_dir, f"{ticker}_all_patterns.png")
    plt.savefig(chart_path)
    print(f"所有圖形模式綜合圖表已保存至 {chart_path}")
    
    # 保存最近時期的圖表
    chart_path = os.path.join(stock_dir, f"{ticker}_recent_patterns.png")
    plt.savefig(chart_path)
    print(f"最近時期的圖形模式圖表已保存至 {chart_path}")
    
    print("\n擴展圖形模式識別測試完成！")

if __name__ == "__main__":
    test_extended_patterns() 