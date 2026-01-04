import os
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from data_module import DataLoader, DataProcessor
from analysis_module.pattern_analysis import PatternAnalyzer

# 設定中文字體
def set_chinese_font():
    """設定中文字體"""
    # 嘗試設定微軟正黑體（適用於Windows）
    try:
        plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'SimHei', 'Arial Unicode MS']
        plt.rcParams['axes.unicode_minus'] = False  # 解決負號顯示問題
        print("已設定中文字體")
    except:
        print("設定中文字體失敗，將使用默認字體")

def test_pattern_analyzer():
    """測試圖形模式分析器的功能"""
    # 設定中文字體
    set_chinese_font()
    
    # 初始化數據加載器和處理器
    data_loader = DataLoader()
    data_processor = DataProcessor()
    pattern_analyzer = PatternAnalyzer()
    
    # 設定股票代碼和數據路徑
    ticker = '2330'  # 台積電
    data_path = r"D:\Min\Python\Project\FA_Data\technical_analysis"
    file_path = os.path.join(data_path, f"{ticker}_indicators.csv")
    
    # 設定測試數據保存路徑
    test_data_path = r"D:\Min\Python\Project\FA_Data\test_data"
    stock_dir = os.path.join(test_data_path, ticker)
    os.makedirs(stock_dir, exist_ok=True)
    
    # 檢查文件是否存在
    if not os.path.exists(file_path):
        print(f"錯誤: 找不到文件 {file_path}")
        return
    
    # 加載數據
    print(f"正在加載 {ticker} 的歷史數據...")
    try:
        df = data_loader.load_from_csv(file_path)
        print(f"成功加載數據，共 {len(df)} 筆記錄")
        
        # 顯示欄位數量和名稱
        print(f"數據欄位數量: {len(df.columns)}")
        print("數據欄位:")
        for i, col in enumerate(df.columns, 1):
            print(f"{i}. {col}")
    except Exception as e:
        print(f"加載數據時出錯: {str(e)}")
        return
    
    # 處理日期列
    print("\n正在處理日期列...")
    try:
        # 檢查是否有日期列
        if '日期' in df.columns:
            print(f"找到日期列，前5個值: {df['日期'].head().tolist()}")
            
            # 嘗試 YYYY-MM-DD 格式（根據數據顯示，這是正確的格式）
            df['日期'] = pd.to_datetime(df['日期'], format='%Y-%m-%d', errors='coerce')
            print("使用 %Y-%m-%d 格式轉換日期")
            
            # 檢查轉換後的日期
            print(f"轉換後的日期，前5個值: {df['日期'].head().tolist()}")
            
            # 檢查是否有 NaT (Not a Time) 值
            nat_count = df['日期'].isna().sum()
            if nat_count > 0:
                print(f"警告: 有 {nat_count} 個日期無法轉換")
            
            # 將日期列設為索引
            df = df.set_index('日期')
            print("已將日期列設為索引")
        else:
            print("警告: 找不到日期列，將使用默認索引")
    except Exception as e:
        print(f"處理日期列時出錯: {str(e)}")
        import traceback
        traceback.print_exc()
    
    # 數據預處理
    print("\n正在進行數據預處理...")
    df_cleaned = data_processor.clean_data(df)
    
    # 測試圖形模式識別
    print("\n正在測試圖形模式識別...")
    
    # 創建一個圖表字典，用於存儲不同類型的圖表
    chart_dict = {}
    
    # 測試 W底 識別
    print("\n正在識別 W底 形態...")
    w_bottom_positions = pattern_analyzer.identify_pattern(df_cleaned, 'W底', window=30, threshold=0.1)
    print(f"找到 {len(w_bottom_positions)} 個 W底 形態")
    
    if w_bottom_positions:
        # 繪製 W底 形態（合併到一個圖表中）
        print("正在繪製 W底 形態...")
        plt.figure(figsize=(12, 6))
        plt.plot(df_cleaned.index, df_cleaned['收盤價'], label='收盤價')
        
        # 標記識別出的 W底 形態
        for i, (start_idx, end_idx) in enumerate(w_bottom_positions):
            # 只標記最近的 20 個形態，避免圖表過於擁擠
            if i >= len(w_bottom_positions) - 20:
                plt.axvspan(df_cleaned.index[start_idx], df_cleaned.index[end_idx], alpha=0.2, color='red')
                # 只在每 5 個形態上添加標籤，避免標籤重疊
                if i % 5 == 0:
                    plt.text(df_cleaned.index[start_idx], df_cleaned['收盤價'].iloc[start_idx], 'W底', 
                             fontsize=10, color='red')
        
        plt.title(f'{ticker} - W底 形態識別 (共 {len(w_bottom_positions)} 個)')
        plt.legend()
        plt.grid(True)
        
        # 保存圖表
        chart_path = os.path.join(stock_dir, f"{ticker}_w_bottom.png")
        plt.savefig(chart_path)
        print(f"W底形態圖表已保存至 {chart_path}")
        
        # 將圖表對象保存到字典中
        chart_dict['W底'] = plt.gcf()
        
        # 根據 W底 形態進行預測
        print("\n正在根據 W底 形態進行預測...")
        # 只使用最後一個 W底 形態進行預測
        last_w_bottom = [w_bottom_positions[-1]]
        forecast_df = pattern_analyzer.predict_from_pattern(df_cleaned, last_w_bottom, 'W底', forecast_periods=30)
        
        if forecast_df is not None:
            # 繪製預測結果
            plt.figure(figsize=(12, 6))
            plt.plot(df_cleaned.index[-100:], df_cleaned['收盤價'].iloc[-100:], label='歷史收盤價')
            plt.plot(forecast_df.index, forecast_df['收盤價'], label='預測收盤價', linestyle='--', color='red')
            plt.title(f'{ticker} - 基於最近的 W底 形態的價格預測')
            plt.legend()
            plt.grid(True)
            
            # 保存預測圖表
            forecast_chart_path = os.path.join(stock_dir, f"{ticker}_w_bottom_forecast.png")
            plt.savefig(forecast_chart_path)
            print(f"W底形態預測圖表已保存至 {forecast_chart_path}")
            
            # 將預測圖表對象保存到字典中
            chart_dict['W底_預測'] = plt.gcf()
    
    # 測試 頭肩頂 識別
    print("\n正在識別 頭肩頂 形態...")
    hs_top_positions = pattern_analyzer.identify_pattern(df_cleaned, '頭肩頂', window=50, threshold=0.15)
    print(f"找到 {len(hs_top_positions)} 個 頭肩頂 形態")
    
    if hs_top_positions:
        # 繪製 頭肩頂 形態（合併到一個圖表中）
        print("正在繪製 頭肩頂 形態...")
        plt.figure(figsize=(12, 6))
        plt.plot(df_cleaned.index, df_cleaned['收盤價'], label='收盤價')
        
        # 標記識別出的 頭肩頂 形態
        for i, (start_idx, end_idx) in enumerate(hs_top_positions):
            # 只標記最近的 20 個形態，避免圖表過於擁擠
            if i >= len(hs_top_positions) - 20:
                plt.axvspan(df_cleaned.index[start_idx], df_cleaned.index[end_idx], alpha=0.2, color='blue')
                # 只在每 5 個形態上添加標籤，避免標籤重疊
                if i % 5 == 0:
                    plt.text(df_cleaned.index[start_idx], df_cleaned['收盤價'].iloc[start_idx], '頭肩頂', 
                             fontsize=10, color='blue')
        
        plt.title(f'{ticker} - 頭肩頂 形態識別 (共 {len(hs_top_positions)} 個)')
        plt.legend()
        plt.grid(True)
        
        # 保存圖表
        chart_path = os.path.join(stock_dir, f"{ticker}_head_and_shoulders_top.png")
        plt.savefig(chart_path)
        print(f"頭肩頂形態圖表已保存至 {chart_path}")
        
        # 將圖表對象保存到字典中
        chart_dict['頭肩頂'] = plt.gcf()
        
        # 根據 頭肩頂 形態進行預測
        print("\n正在根據 頭肩頂 形態進行預測...")
        # 只使用最後一個 頭肩頂 形態進行預測
        last_hs_top = [hs_top_positions[-1]]
        forecast_df = pattern_analyzer.predict_from_pattern(df_cleaned, last_hs_top, '頭肩頂', forecast_periods=30)
        
        if forecast_df is not None:
            # 繪製預測結果
            plt.figure(figsize=(12, 6))
            plt.plot(df_cleaned.index[-100:], df_cleaned['收盤價'].iloc[-100:], label='歷史收盤價')
            plt.plot(forecast_df.index, forecast_df['收盤價'], label='預測收盤價', linestyle='--', color='blue')
            plt.title(f'{ticker} - 基於最近的 頭肩頂 形態的價格預測')
            plt.legend()
            plt.grid(True)
            
            # 保存預測圖表
            forecast_chart_path = os.path.join(stock_dir, f"{ticker}_head_and_shoulders_top_forecast.png")
            plt.savefig(forecast_chart_path)
            print(f"頭肩頂形態預測圖表已保存至 {forecast_chart_path}")
            
            # 將預測圖表對象保存到字典中
            chart_dict['頭肩頂_預測'] = plt.gcf()
    
    # 測試 頭肩底 識別
    print("\n正在識別 頭肩底 形態...")
    hs_bottom_positions = pattern_analyzer.identify_pattern(df_cleaned, '頭肩底', window=50, threshold=0.15)
    print(f"找到 {len(hs_bottom_positions)} 個 頭肩底 形態")
    
    if hs_bottom_positions:
        # 繪製 頭肩底 形態（合併到一個圖表中）
        print("正在繪製 頭肩底 形態...")
        plt.figure(figsize=(12, 6))
        plt.plot(df_cleaned.index, df_cleaned['收盤價'], label='收盤價')
        
        # 標記識別出的 頭肩底 形態
        for i, (start_idx, end_idx) in enumerate(hs_bottom_positions):
            # 只標記最近的 20 個形態，避免圖表過於擁擠
            if i >= len(hs_bottom_positions) - 20:
                plt.axvspan(df_cleaned.index[start_idx], df_cleaned.index[end_idx], alpha=0.2, color='green')
                # 只在每 5 個形態上添加標籤，避免標籤重疊
                if i % 5 == 0:
                    plt.text(df_cleaned.index[start_idx], df_cleaned['收盤價'].iloc[start_idx], '頭肩底', 
                             fontsize=10, color='green')
        
        plt.title(f'{ticker} - 頭肩底 形態識別 (共 {len(hs_bottom_positions)} 個)')
        plt.legend()
        plt.grid(True)
        
        # 保存圖表
        chart_path = os.path.join(stock_dir, f"{ticker}_head_and_shoulders_bottom.png")
        plt.savefig(chart_path)
        print(f"頭肩底形態圖表已保存至 {chart_path}")
        
        # 將圖表對象保存到字典中
        chart_dict['頭肩底'] = plt.gcf()
        
        # 根據 頭肩底 形態進行預測
        print("\n正在根據 頭肩底 形態進行預測...")
        # 只使用最後一個 頭肩底 形態進行預測
        last_hs_bottom = [hs_bottom_positions[-1]]
        forecast_df = pattern_analyzer.predict_from_pattern(df_cleaned, last_hs_bottom, '頭肩底', forecast_periods=30)
        
        if forecast_df is not None:
            # 繪製預測結果
            plt.figure(figsize=(12, 6))
            plt.plot(df_cleaned.index[-100:], df_cleaned['收盤價'].iloc[-100:], label='歷史收盤價')
            plt.plot(forecast_df.index, forecast_df['收盤價'], label='預測收盤價', linestyle='--', color='green')
            plt.title(f'{ticker} - 基於最近的 頭肩底 形態的價格預測')
            plt.legend()
            plt.grid(True)
            
            # 保存預測圖表
            forecast_chart_path = os.path.join(stock_dir, f"{ticker}_head_and_shoulders_bottom_forecast.png")
            plt.savefig(forecast_chart_path)
            print(f"頭肩底形態預測圖表已保存至 {forecast_chart_path}")
            
            # 將預測圖表對象保存到字典中
            chart_dict['頭肩底_預測'] = plt.gcf()
    
    # 創建一個綜合圖表，顯示所有形態
    print("\n正在創建綜合圖表...")
    plt.figure(figsize=(15, 8))
    
    # 選擇最近的形態
    recent_count = 20  # 每種形態顯示的數量
    patterns = {
        'W底': w_bottom_positions[-recent_count:] if len(w_bottom_positions) >= recent_count else w_bottom_positions,
        '頭肩頂': hs_top_positions[-recent_count:] if len(hs_top_positions) >= recent_count else hs_top_positions,
        '頭肩底': hs_bottom_positions[-recent_count:] if len(hs_bottom_positions) >= recent_count else hs_bottom_positions
    }
    
    # 找出最早和最晚的形態索引，用於限制時間軸
    all_positions = []
    for positions in patterns.values():
        all_positions.extend(positions)
    
    if all_positions:
        # 找出最早和最晚的形態索引
        earliest_idx = min([start_idx for start_idx, _ in all_positions])
        latest_idx = max([end_idx for _, end_idx in all_positions])
        
        # 添加一些邊距，使圖表更美觀
        margin = int((latest_idx - earliest_idx) * 0.1)  # 10% 的邊距
        plot_start_idx = max(0, earliest_idx - margin)
        plot_end_idx = min(len(df_cleaned) - 1, latest_idx + margin)
        
        # 繪製限定範圍內的價格
        plt.plot(df_cleaned.index[plot_start_idx:plot_end_idx+1], 
                 df_cleaned['收盤價'].iloc[plot_start_idx:plot_end_idx+1], 
                 label='收盤價')
        
        # 標記所有形態
        colors = {'W底': 'red', '頭肩頂': 'blue', '頭肩底': 'green'}
        for pattern_type, positions in patterns.items():
            for i, (start_idx, end_idx) in enumerate(positions):
                plt.axvspan(df_cleaned.index[start_idx], df_cleaned.index[end_idx], 
                           alpha=0.2, color=colors[pattern_type])
                # 添加標籤，避免重疊
                if i % 3 == 0:  # 每 3 個形態添加一個標籤
                    plt.text(df_cleaned.index[start_idx], 
                            df_cleaned['收盤價'].iloc[start_idx], 
                            pattern_type, 
                            fontsize=10, color=colors[pattern_type])
        
        plt.title(f'{ticker} - 最近 {recent_count} 個圖形模式 (時間範圍: {df_cleaned.index[plot_start_idx].strftime("%Y-%m-%d")} 至 {df_cleaned.index[plot_end_idx].strftime("%Y-%m-%d")})')
        plt.legend()
        plt.grid(True)
        
        # 保存綜合圖表
        combined_chart_path = os.path.join(stock_dir, f"{ticker}_recent_patterns.png")
        plt.savefig(combined_chart_path)
        print(f"最近形態綜合圖表已保存至 {combined_chart_path}")
        
        # 將綜合圖表對象保存到字典中
        chart_dict['最近形態'] = plt.gcf()
    else:
        print("未找到任何形態，無法創建綜合圖表")
    
    # 創建一個全部數據的綜合圖表（僅用於參考）
    print("\n正在創建全部數據的綜合圖表...")
    plt.figure(figsize=(15, 8))
    plt.plot(df_cleaned.index, df_cleaned['收盤價'], label='收盤價')
    
    # 標記所有形態，但透明度降低
    all_patterns = {
        'W底': w_bottom_positions,
        '頭肩頂': hs_top_positions,
        '頭肩底': hs_bottom_positions
    }
    
    for pattern_type, positions in all_patterns.items():
        for start_idx, end_idx in positions:
            plt.axvspan(df_cleaned.index[start_idx], df_cleaned.index[end_idx], 
                       alpha=0.05, color=colors[pattern_type])
    
    plt.title(f'{ticker} - 所有圖形模式 (共 {len(w_bottom_positions) + len(hs_top_positions) + len(hs_bottom_positions)} 個)')
    plt.legend()
    plt.grid(True)
    
    # 保存全部數據的綜合圖表
    all_patterns_chart_path = os.path.join(stock_dir, f"{ticker}_all_patterns.png")
    plt.savefig(all_patterns_chart_path)
    print(f"全部數據的綜合圖表已保存至 {all_patterns_chart_path}")
    
    # 將全部數據的綜合圖表對象保存到字典中
    chart_dict['所有形態'] = plt.gcf()
    
    # 評估圖形模式預測的準確性
    print("\n正在評估圖形模式預測的準確性...")
    
    # 評估 W底 形態
    w_bottom_accuracy = pattern_analyzer.evaluate_pattern_accuracy(df_cleaned, 'W底', window=30, threshold=0.1)
    if w_bottom_accuracy:
        print(f"W底 形態預測準確性評估結果:")
        print(f"- 識別出的形態數量: {w_bottom_accuracy['num_patterns']}")
        print(f"- 平均均方誤差 (MSE): {w_bottom_accuracy['avg_mse']:.4f}")
        print(f"- 平均絕對誤差 (MAE): {w_bottom_accuracy['avg_mae']:.4f}")
        print(f"- 方向準確率: {w_bottom_accuracy['direction_accuracy']:.2%}")
    
    # 評估 頭肩頂 形態
    hs_top_accuracy = pattern_analyzer.evaluate_pattern_accuracy(df_cleaned, '頭肩頂', window=50, threshold=0.15)
    if hs_top_accuracy:
        print(f"\n頭肩頂 形態預測準確性評估結果:")
        print(f"- 識別出的形態數量: {hs_top_accuracy['num_patterns']}")
        print(f"- 平均均方誤差 (MSE): {hs_top_accuracy['avg_mse']:.4f}")
        print(f"- 平均絕對誤差 (MAE): {hs_top_accuracy['avg_mae']:.4f}")
        print(f"- 方向準確率: {hs_top_accuracy['direction_accuracy']:.2%}")
    
    # 評估 頭肩底 形態
    hs_bottom_accuracy = pattern_analyzer.evaluate_pattern_accuracy(df_cleaned, '頭肩底', window=50, threshold=0.15)
    if hs_bottom_accuracy:
        print(f"\n頭肩底 形態預測準確性評估結果:")
        print(f"- 識別出的形態數量: {hs_bottom_accuracy['num_patterns']}")
        print(f"- 平均均方誤差 (MSE): {hs_bottom_accuracy['avg_mse']:.4f}")
        print(f"- 平均絕對誤差 (MAE): {hs_bottom_accuracy['avg_mae']:.4f}")
        print(f"- 方向準確率: {hs_bottom_accuracy['direction_accuracy']:.2%}")
    
    print("\n圖形模式分析測試完成")

if __name__ == "__main__":
    test_pattern_analyzer() 