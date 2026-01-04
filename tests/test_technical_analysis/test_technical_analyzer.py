import os
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np
from data_module import DataLoader, DataProcessor
from analysis_module.technical_analysis import TechnicalAnalyzer

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

def test_technical_analyzer():
    """測試技術分析器的功能"""
    # 設定中文字體
    set_chinese_font()
    
    # 初始化數據加載器和處理器
    data_loader = DataLoader()
    data_processor = DataProcessor()
    
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
            
            # 檢查是否有其他可能的日期列
            date_like_cols = [col for col in df.columns if '日' in col or '時間' in col or 'date' in col.lower() or 'time' in col.lower()]
            if date_like_cols:
                print(f"發現可能的日期列: {date_like_cols}")
                
                # 嘗試使用第一個可能的日期列
                date_col = date_like_cols[0]
                print(f"嘗試使用 {date_col} 作為日期列，前5個值: {df[date_col].head().tolist()}")
                
                # 嘗試轉換為日期
                try:
                    df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
                    print(f"轉換後的日期，前5個值: {df[date_col].head().tolist()}")
                    
                    # 將日期列設為索引
                    df = df.set_index(date_col)
                    print(f"已將 {date_col} 設為索引")
                except Exception as e:
                    print(f"轉換日期時出錯: {str(e)}")
    except Exception as e:
        print(f"處理日期列時出錯: {str(e)}")
        import traceback
        traceback.print_exc()
    
    # 數據預處理
    print("\n正在進行數據預處理...")
    df_cleaned = data_processor.clean_data(df)
    
    # 檢查現有的技術指標
    print("\n檢查現有的技術指標...")
    tech_indicators = [col for col in df_cleaned.columns if col in ['SMA30', 'DEMA30', 'EMA30', 'RSI', 'MACD', 'MACD_signal', 'MACD_hist', 'slowk', 'slowd', 'TSF', 'middleband', 'SAR']]
    print(f"找到 {len(tech_indicators)} 個技術指標:")
    for i, indicator in enumerate(tech_indicators, 1):
        print(f"{i}. {indicator}")
    
    # 繪製技術指標圖表
    print("\n正在繪製技術指標圖表...")
    try:
        # 只選擇最近100天的數據進行繪製，避免圖表過於擁擠
        df_plot = df_cleaned.iloc[-100:]
        
        plt.figure(figsize=(12, 10))
        
        # 繪製價格圖
        plt.subplot(3, 1, 1)
        plt.plot(df_plot.index, df_plot['收盤價'], label='收盤價')
        if 'SMA30' in df_plot.columns:
            plt.plot(df_plot.index, df_plot['SMA30'], label='30日均線')
        if 'EMA30' in df_plot.columns:
            plt.plot(df_plot.index, df_plot['EMA30'], label='30日指數均線')
        plt.title(f'{ticker} 價格和均線')
        plt.legend()
        plt.grid(True)
        
        # 繪製RSI圖
        if 'RSI' in df_plot.columns:
            plt.subplot(3, 1, 2)
            plt.plot(df_plot.index, df_plot['RSI'], label='RSI')
            plt.axhline(y=70, color='r', linestyle='-', alpha=0.3)
            plt.axhline(y=30, color='g', linestyle='-', alpha=0.3)
            plt.title('RSI 指標')
            plt.legend()
            plt.grid(True)
        
        # 繪製MACD圖
        if 'MACD' in df_plot.columns and 'MACD_signal' in df_plot.columns:
            plt.subplot(3, 1, 3)
            plt.plot(df_plot.index, df_plot['MACD'], label='MACD')
            plt.plot(df_plot.index, df_plot['MACD_signal'], label='MACD信號線')
            plt.title('MACD 指標')
            plt.legend()
            plt.grid(True)
        
        plt.tight_layout()
        
        # 保存圖表到文件
        chart_path = os.path.join(stock_dir, f"{ticker}_technical_indicators.png")
        plt.savefig(chart_path)
        print(f"圖表已保存至 {chart_path}")
        
        # 在非交互式環境中，不顯示圖表
        # plt.show()
        
        # 保存處理後的數據
        save_processed = input("\n是否保存處理後的數據? (y/n): ").lower() == 'y'
        if save_processed:
            output_path = os.path.join(stock_dir, f"{ticker}_processed.csv")
            df_cleaned.to_csv(output_path, encoding='utf-8-sig', index=True)
            print(f"處理後的數據已保存至 {output_path}")
    
    except Exception as e:
        print(f"處理技術指標時出錯: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_technical_analyzer() 