import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
from analysis_module.technical_analyzer import TechnicalAnalyzer
from analysis_module.pattern_analyzer import PatternAnalyzer

def set_chinese_font():
    """設定中文字體"""
    # 嘗試設定微軟正黑體（適用於Windows）
    try:
        plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'SimHei', 'Arial Unicode MS']
        plt.rcParams['axes.unicode_minus'] = False  # 解決負號顯示問題
        print("已設定中文字體")
    except:
        print("設定中文字體失敗，將使用默認字體")

# 設置測試數據路徑
TEST_DATA_PATH = r'D:\Min\Python\Project\FA_Data\test_data'
# 設置測試結果路徑
TEST_RESULTS_PATH = r'D:\Min\Python\Project\FA_Data\test_data'

# 確保測試數據和結果目錄存在
os.makedirs(TEST_DATA_PATH, exist_ok=True)
os.makedirs(TEST_RESULTS_PATH, exist_ok=True)

def load_test_data():
    """加載測試數據"""
    try:
        # 嘗試加載市場指數數據
        market_index_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_data", "market_index.csv")
        print(f"嘗試從以下路徑加載數據：{market_index_path}")
        df = pd.read_csv(market_index_path, encoding='utf-8-sig')
        print(f"成功加載市場指數數據，時間範圍：{df['Date'].min()} 至 {df['Date'].max()}")
        
        # 檢查並設置日期索引
        if 'Date' in df.columns:
            df['Date'] = pd.to_datetime(df['Date'])
            df.set_index('Date', inplace=True)
        elif not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.date_range(start='2020-01-01', periods=len(df), freq='D')
        
        # 檢查必要欄位
        required_columns = ['Open', 'High', 'Low', 'Close', 'Volume']
        for col in required_columns:
            if col not in df.columns:
                # 檢查中文列名
                chinese_cols = {
                    'Open': ['開盤價', '開盤'],
                    'High': ['最高價', '最高'],
                    'Low': ['最低價', '最低'],
                    'Close': ['收盤價', '收盤'],
                    'Volume': ['成交量', '成交股數']
                }
                
                found = False
                for chinese_col in chinese_cols[col]:
                    if chinese_col in df.columns:
                        df[col] = df[chinese_col]
                        found = True
                        break
                
                if not found:
                    # 如果是成交量，使用隨機數據
                    if col == 'Volume':
                        df[col] = np.random.randint(100000, 10000000, size=len(df))
                    else:
                        raise ValueError(f"缺少必要的列：{col}")
        
        return df
        
    except Exception as e:
        print(f"加載數據時出錯：{str(e)}")
        print("生成模擬數據...")
        # 生成模擬數據
        dates = pd.date_range(start='2020-01-01', periods=500, freq='D')
        df = pd.DataFrame(index=dates)
        
        # 生成價格數據
        initial_price = 100.0
        prices = [initial_price]
        for _ in range(1, len(dates)):
            change_pct = np.random.normal(0, 0.015)  # 每日價格變動率服從正態分布
            new_price = prices[-1] * (1 + change_pct)
            prices.append(new_price)
        
        df['Close'] = prices
        df['Open'] = df['Close'] * (1 + np.random.normal(0, 0.005, len(df)))
        df['High'] = df[['Open', 'Close']].max(axis=1) * (1 + abs(np.random.normal(0, 0.003, len(df))))
        df['Low'] = df[['Open', 'Close']].min(axis=1) * (1 - abs(np.random.normal(0, 0.003, len(df))))
        df['Volume'] = np.random.randint(100000, 10000000, size=len(df))
        
        return df

def test_parameter_combinations(df, pattern_type):
    """測試不同參數組合對圖形模式識別的影響"""
    results = []
    pa = PatternAnalyzer()
    
    try:
        if pattern_type == 'W底':
            # 測試W底形態的參數組合
            windows = [10, 15, 20, 25, 30]  # 更小的窗口大小
            thresholds = [0.03, 0.05, 0.08, 0.1]  # 更小的閾值
            prominences = [0.3, 0.5, 0.8, 1.0]  # 更小的prominence值
            
            for window in windows:
                for threshold in thresholds:
                    for prominence in prominences:
                        try:
                            # 使用 identify_pattern 方法識別W底形態
                            patterns = pa.identify_pattern(df, pattern_type, window=window, threshold=threshold, prominence=prominence)
                            
                            # 計算準確率（如果在20天內價格上漲超過2%，則認為是正確的）
                            accuracy = 0
                            if patterns:
                                correct_count = 0
                                for pattern in patterns:
                                    end_idx = pattern['end_idx']
                                    if end_idx + 20 < len(df):
                                        future_return = (df['Close'].iloc[end_idx + 20] - df['Close'].iloc[end_idx]) / df['Close'].iloc[end_idx]
                                        if future_return > 0.02:
                                            correct_count += 1
                                accuracy = (correct_count / len(patterns)) * 100 if len(patterns) > 0 else 0
                            
                            results.append({
                                'pattern_type': pattern_type,
                                'window': window,
                                'threshold': threshold,
                                'prominence': prominence,
                                'patterns_count': len(patterns) if patterns else 0,
                                'accuracy': accuracy
                            })
                        except Exception as e:
                            print(f"測試W底參數組合時出錯 (window={window}, threshold={threshold}, prominence={prominence}): {str(e)}")
                            continue
                        
        elif pattern_type == '頭肩頂':
            # 測試頭肩頂形態的參數組合
            windows = [20, 25, 30, 35, 40]  # 更大的窗口大小
            thresholds = [0.05, 0.08, 0.1, 0.15]  # 更大的閾值
            
            for window in windows:
                for threshold in thresholds:
                    try:
                        # 使用 identify_pattern 方法識別頭肩頂形態
                        patterns = pa.identify_pattern(df, pattern_type, window=window, threshold=threshold)
                        
                        # 計算準確率（如果在20天內價格下跌超過2%，則認為是正確的）
                        accuracy = 0
                        if patterns:
                            correct_count = 0
                            for pattern in patterns:
                                end_idx = pattern['end_idx']
                                if end_idx + 20 < len(df):
                                    future_return = (df['Close'].iloc[end_idx + 20] - df['Close'].iloc[end_idx]) / df['Close'].iloc[end_idx]
                                    if future_return < -0.02:
                                        correct_count += 1
                            accuracy = (correct_count / len(patterns)) * 100 if len(patterns) > 0 else 0
                        
                        results.append({
                            'pattern_type': pattern_type,
                            'window': window,
                            'threshold': threshold,
                            'patterns_count': len(patterns) if patterns else 0,
                            'accuracy': accuracy
                        })
                    except Exception as e:
                        print(f"測試頭肩頂參數組合時出錯 (window={window}, threshold={threshold}): {str(e)}")
                        continue
                        
        elif pattern_type == '三角形':
            # 測試三角形形態的參數組合
            windows = [20, 25, 30]  # 更大的窗口大小
            thresholds = [0.05, 0.08]  # 更大的閾值
            min_r_squareds = [0.4, 0.5]  # 更大的R方值
            min_height_ratios = [0.02, 0.03]  # 更大的高度比例
            
            # 對數據進行預處理
            df_processed = df.copy()
            # 計算價格的標準化值
            price_mean = df_processed['Close'].mean()
            price_std = df_processed['Close'].std()
            df_processed['Close'] = (df_processed['Close'] - price_mean) / price_std
            
            for window in windows:
                for threshold in thresholds:
                    for min_r_squared in min_r_squareds:
                        for min_height_ratio in min_height_ratios:
                            try:
                                # 使用 identify_pattern 方法識別三角形形態
                                patterns = pa.identify_pattern(df_processed, pattern_type, window=window, threshold=threshold, 
                                                            min_r_squared=min_r_squared, min_height_ratio=min_height_ratio)
                                
                                # 計算準確率（如果在20天內價格變動超過2%，則認為是正確的）
                                accuracy = 0
                                if patterns:
                                    correct_count = 0
                                    for pattern in patterns:
                                        end_idx = pattern['end_idx']
                                        if end_idx + 20 < len(df):
                                            future_return = abs((df['Close'].iloc[end_idx + 20] - df['Close'].iloc[end_idx]) / df['Close'].iloc[end_idx])
                                            if future_return > 0.02:
                                                correct_count += 1
                                    accuracy = (correct_count / len(patterns)) * 100 if len(patterns) > 0 else 0
                                
                                results.append({
                                    'pattern_type': pattern_type,
                                    'window': window,
                                    'threshold': threshold,
                                    'min_r_squared': min_r_squared,
                                    'min_height_ratio': min_height_ratio,
                                    'patterns_count': len(patterns) if patterns else 0,
                                    'accuracy': accuracy
                                })
                            except Exception as e:
                                print(f"測試三角形參數組合時出錯 (window={window}, threshold={threshold}, min_r_squared={min_r_squared}, min_height_ratio={min_height_ratio}): {str(e)}")
                                continue
    
    except Exception as e:
        print(f"測試參數組合時出錯：{str(e)}")
    
    return results

def plot_parameter_results(results, output_dir):
    """繪製參數測試結果圖表
    
    Args:
        results: 測試結果列表
        output_dir: 輸出目錄
    """
    # 設置中文字體
    set_chinese_font()
    
    # 按模式類型分組結果
    pattern_results = {}
    for result in results:
        pattern_type = result['pattern_type']
        if pattern_type not in pattern_results:
            pattern_results[pattern_type] = []
        pattern_results[pattern_type].append(result)
    
    # 為每種模式類型創建圖表
    for pattern_type, pattern_data in pattern_results.items():
        if not pattern_data:
            continue
            
        # 創建圖表
        plt.figure(figsize=(15, 6))
        
        # 繪製識別數量柱狀圖
        plt.subplot(1, 2, 1)
        x = range(len(pattern_data))
        patterns_count = [r['patterns_count'] for r in pattern_data]
        plt.bar(x, patterns_count)
        plt.title(f'{pattern_type} 識別數量')
        plt.xlabel('參數組合編號')
        plt.ylabel('識別數量')
        plt.xticks(x, [str(i+1) for i in x])
        
        # 繪製準確率柱狀圖
        plt.subplot(1, 2, 2)
        accuracy = [r['accuracy'] for r in pattern_data]
        plt.bar(x, accuracy)
        plt.title(f'{pattern_type} 準確率')
        plt.xlabel('參數組合編號')
        plt.ylabel('準確率 (%)')
        plt.xticks(x, [str(i+1) for i in x])
        
        # 保存圖表
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, f'{pattern_type}_results.png'))
        plt.close()
        
        # 保存參數組合和結果到文本文件
        with open(os.path.join(output_dir, f'{pattern_type}_results.txt'), 'w', encoding='utf-8') as f:
            f.write(f'{pattern_type} 參數測試結果:\n\n')
            for i, result in enumerate(pattern_data, 1):
                f.write(f'參數組合 {i}:\n')
                for key, value in result.items():
                    if key != 'pattern_type':
                        if key in ['accuracy', 'patterns_count']:
                            f.write(f'{key}: {value:.2f}\n')
                        else:
                            f.write(f'{key}: {value}\n')
                f.write('\n')

def main():
    # 設置測試數據路徑
    test_data_path = r'D:\Min\Python\Project\FA_Data\test_data'
    os.makedirs(test_data_path, exist_ok=True)
    
    # 設置股票代碼
    ticker = '2330'  # 可以根據需要修改
    
    # 創建股票專屬的資料夾
    stock_dir = os.path.join(test_data_path, ticker)
    os.makedirs(stock_dir, exist_ok=True)
    
    # 加載數據
    print("正在加載數據...")
    df = load_test_data()
    
    # 創建時間戳目錄
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    results_dir = os.path.join(stock_dir, f'pattern_parameter_tuning_{timestamp}')
    os.makedirs(results_dir, exist_ok=True)
    
    # 保存測試數據
    df.to_csv(os.path.join(results_dir, 'test_data.csv'), index=False)
    
    # 測試不同圖形模式
    pattern_types = ['W底', '頭肩頂', '三角形']
    all_results = []
    
    for pattern_type in pattern_types:
        print(f"測試 {pattern_type} 模式...")
        results = test_parameter_combinations(df, pattern_type)
        all_results.extend(results)
        
        # 找出最佳參數組合
        if results:
            best_result = max(results, key=lambda x: x['accuracy'])
            print(f"最佳參數組合:")
            for key, value in best_result.items():
                if key not in ['patterns_count', 'accuracy']:
                    print(f"- {key}: {value}")
            print(f"識別數量: {best_result['patterns_count']}")
            print(f"準確率: {best_result['accuracy']:.2f}%")
    
    # 繪製結果圖表
    plot_parameter_results(all_results, results_dir)
    
    print(f"\n所有測試結果已保存至: {results_dir}")

if __name__ == '__main__':
    main() 