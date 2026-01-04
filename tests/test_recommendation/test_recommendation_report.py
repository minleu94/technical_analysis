import os
import pandas as pd
from data_module import DataLoader, DataProcessor
from analysis_module.technical_analysis import TechnicalAnalyzer
from analysis_module.ml_analysis import MLAnalyzer
from analysis_module.technical_analysis import MathAnalyzer
# from recommendation_module import RecommendationEngine
from recommendation_module_legacy import RecommendationEngine

def test_recommendation_report():
    """測試生成推薦報告並檢查編碼"""
    # 初始化各模組
    data_loader = DataLoader()
    data_processor = DataProcessor()
    tech_analyzer = TechnicalAnalyzer()
    ml_analyzer = MLAnalyzer()
    math_analyzer = MathAnalyzer()
    
    # 設定股票代碼和數據路徑
    ticker = '2330'  # 台積電
    data_path = r"D:\Min\Python\Project\FA_Data\technical_analysis"
    file_path = os.path.join(data_path, f"{ticker}_indicators.csv")
    
    # 設定測試數據保存路徑
    test_data_path = r"D:\Min\Python\Project\FA_Data\test_data"
    if not os.path.exists(test_data_path):
        os.makedirs(test_data_path)
    
    # 加載數據
    print(f"正在加載 {ticker} 的歷史數據...")
    df = data_loader.load_from_csv(file_path)
    print(f"成功加載數據，共 {len(df)} 筆記錄")
    
    # 數據預處理
    print("正在進行數據預處理...")
    df_cleaned = data_processor.clean_data(df)
    
    # 計算技術指標
    print("正在計算技術指標...")
    df_tech = tech_analyzer.add_momentum_indicators(df_cleaned)
    df_tech = tech_analyzer.add_volatility_indicators(df_tech)
    df_tech = tech_analyzer.add_trend_indicators(df_tech)
    
    # 初始化推薦引擎
    recommendation_engine = RecommendationEngine(
        technical_analyzer=tech_analyzer,
        ml_analyzer=ml_analyzer,
        math_analyzer=math_analyzer
    )
    
    # 生成報告
    print("正在生成推薦報告...")
    report = recommendation_engine.generate_report(ticker, df_tech)
    
    # 檢查報告文件
    report_path = os.path.join(test_data_path, f"{ticker}_recommendation_report.txt")
    print(f"檢查報告文件: {report_path}")
    
    try:
        # 使用utf-8-sig編碼讀取報告
        with open(report_path, 'r', encoding='utf-8-sig') as f:
            report_content = f.read()
            print("成功讀取報告文件，內容如下:")
            print("-" * 50)
            print(report_content)
            print("-" * 50)
    except UnicodeDecodeError:
        print("使用utf-8-sig編碼讀取失敗，嘗試使用utf-8編碼...")
        try:
            with open(report_path, 'r', encoding='utf-8') as f:
                report_content = f.read()
                print("成功使用utf-8編碼讀取報告文件，內容如下:")
                print("-" * 50)
                print(report_content)
                print("-" * 50)
        except UnicodeDecodeError:
            print("使用utf-8編碼讀取失敗，嘗試使用big5編碼...")
            try:
                with open(report_path, 'r', encoding='big5') as f:
                    report_content = f.read()
                    print("成功使用big5編碼讀取報告文件，內容如下:")
                    print("-" * 50)
                    print(report_content)
                    print("-" * 50)
            except Exception as e:
                print(f"讀取報告文件失敗: {str(e)}")
    
    print("測試完成!")

if __name__ == "__main__":
    test_recommendation_report() 