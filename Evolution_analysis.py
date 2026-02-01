#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Requests库双维度分析：历史提交信息统计 + Bug提交规律分析
【最终稳定版】修复_rebuild()错误+中文显示正常+无警告
"""
import requests
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib as mpl
from matplotlib.font_manager import FontProperties
from datetime import datetime
from dateutil.relativedelta import relativedelta
import os
import platform
import warnings

# ========== 核心修复1：关闭所有Matplotlib相关警告 ==========
warnings.filterwarnings('ignore', category=UserWarning, module='matplotlib')
warnings.filterwarnings('ignore', category=DeprecationWarning, module='matplotlib')

# ========== 核心修复2：强制配置中文字体（适配所有Matplotlib版本） ==========
def force_set_chinese_font():
    """强制设置中文字体，绕过PyCharm后端限制，适配新旧版Matplotlib"""
    # 方案1：直接指定系统中文字体（Windows优先）
    font_paths = {
        "Windows": ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"],  # 微软雅黑/黑体（备选）
        "macOS": ["/System/Library/Fonts/PingFang.ttc", "/Library/Fonts/Heiti TC.ttc"],  # 苹方/黑体
        "Linux": ["/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]  # 文泉驿/兜底
    }

    system = platform.system()
    font_prop = None

    # 优先加载字体文件（解决PyCharm后端字体锁定问题）
    try:
        if system in font_paths:
            for font_path in font_paths[system]:
                if os.path.exists(font_path):
                    font_prop = FontProperties(fname=font_path)
                    plt.rcParams['font.family'] = font_prop.get_name()
                    break
        # 兜底：使用系统已安装的中文字体名称
        if font_prop is None:
            font_names = ['Microsoft YaHei', 'SimHei', 'PingFang SC', 'WenQuanYi Zen Hei']
            for name in font_names:
                try:
                    font_prop = FontProperties(name=name)
                    plt.rcParams['font.family'] = font_prop.get_name()
                    break
                except:
                    continue
    except:
        # 终极兜底：混合字体，保证中文能显示
        plt.rcParams['font.family'] = ['SimHei', 'DejaVu Sans']

    # 解决负号显示问题（中文图表必备）
    plt.rcParams['axes.unicode_minus'] = False

    # 适配新旧版Matplotlib的字体缓存刷新（核心修复：移除_rebuild()，改用兼容写法）
    try:
        # 新版Matplotlib（3.8+）推荐写法
        mpl.font_manager.fontManager.addfont(font_path)
    except:
        try:
            # 旧版Matplotlib兼容
            if hasattr(mpl.font_manager, '_rebuild'):
                mpl.font_manager._rebuild()
        except AttributeError:
            # 无刷新方法则跳过，不影响核心功能
            pass

# 立即执行字体配置（优先级最高）
force_set_chinese_font()

# 禁用SSL警告
requests.packages.urllib3.disable_warnings()

# 项目配置
REPO_OWNER = "psf"
REPO_NAME = "requests"
GITHUB_API_COMMITS = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/commits"
GITHUB_API_ISSUES = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/issues"
PER_PAGE = 50
MAX_PAGES = 5
PROXIES = {
    # "http": "http://127.0.0.1:7890",
    # "https": "http://127.0.0.1:7890"
}

plt.style.use('default')

# ========== 数据拉取层 ==========
def create_session():
    """创建请求会话（处理SSL+代理）"""
    session = requests.Session()
    session.verify = False
    session.timeout = 30
    if PROXIES:
        session.proxies.update(PROXIES)
    return session

def fetch_commits_data():
    """拉取历史提交信息（核心字段：基础信息+衍生维度）"""
    session = create_session()
    commits = []
    print("【数据拉取】开始获取历史提交信息...")
    for page in range(1, MAX_PAGES + 1):
        params = {"per_page": PER_PAGE, "page": page}
        try:
            resp = session.get(GITHUB_API_COMMITS, params=params)
            resp.raise_for_status()
            page_data = resp.json()
            if not page_data:
                break
            for commit in page_data:
                stats = commit.get("stats", {})
                commits.append({
                    "hash": commit["sha"][:8] if "sha" in commit else "",
                    "author": commit["commit"]["author"]["name"] if "commit" in commit else "",
                    "commit_time": pd.to_datetime(commit["commit"]["author"]["date"]).tz_convert(
                        "Asia/Shanghai") if "commit" in commit else None,
                    "message": commit["commit"]["message"].split("\n")[0] if "commit" in commit else "",
                    "files_changed": len(commit.get("files", [])),
                    "insertions": stats.get("additions", 0),
                    "deletions": stats.get("deletions", 0)
                })
            print(f"【数据拉取】提交信息：第{page}页，累计{len(commits)}条")
        except Exception as e:
            print(f"【数据拉取】提交信息拉取失败（页{page}）：{str(e)[:100]}")
            break

    # 数据预处理（新增分析维度）
    df = pd.DataFrame(commits)
    if not df.empty:
        df["commit_type"] = df["message"].apply(classify_commit_type)
        df["commit_time_no_tz"] = df["commit_time"].dt.tz_localize(None)
        df["commit_year"] = df["commit_time_no_tz"].dt.year
        df["commit_month"] = df["commit_time_no_tz"].dt.to_period("M")
        df["total_changes"] = df["insertions"] + df["deletions"]
        df["change_scale"] = pd.cut(
            df["total_changes"],
            bins=[0, 10, 100, 500, float('inf')],
            labels=["小修改(<10行)", "中修改(10-100行)", "大修改(100-500行)", "超大修改(>500行)"]
        )
    return df

def fetch_bugs_data():
    """拉取Bug提交数据（核心字段：基础信息+衍生维度）"""
    session = create_session()
    bugs = []
    print("\n【数据拉取】开始获取Bug提交信息...")
    for page in range(1, MAX_PAGES + 1):
        params = {"per_page": PER_PAGE, "page": page, "labels": "bug", "state": "all"}
        try:
            resp = session.get(GITHUB_API_ISSUES, params=params)
            resp.raise_for_status()
            page_data = resp.json()
            if not page_data:
                break
            for issue in page_data:
                bugs.append({
                    "issue_id": issue["number"] if "number" in issue else "",
                    "title": issue["title"] if "title" in issue else "",
                    "created_time": pd.to_datetime(issue["created_at"]).tz_convert(
                        "Asia/Shanghai") if "created_at" in issue else None,
                    "closed_time": pd.to_datetime(issue["closed_at"]).tz_convert("Asia/Shanghai") if issue.get(
                        "closed_at") else None,
                    "state": issue["state"] if "state" in issue else "",
                    "creator": issue["user"]["login"] if "user" in issue else "",
                    "comments": issue["comments"] if "comments" in issue else 0
                })
            print(f"【数据拉取】Bug信息：第{page}页，累计{len(bugs)}条")
        except Exception as e:
            print(f"【数据拉取】Bug信息拉取失败（页{page}）：{str(e)[:100]}")
            break

    # 数据预处理（新增分析维度）
    df = pd.DataFrame(bugs)
    if not df.empty:
        df["created_time_no_tz"] = df["created_time"].dt.tz_localize(None)
        df["created_year"] = df["created_time_no_tz"].dt.year
        df["created_month"] = df["created_time_no_tz"].dt.to_period("M")
        # 计算修复周期
        closed_bugs_idx = df.dropna(subset=["closed_time", "created_time"]).index
        df.loc[closed_bugs_idx, "fix_duration"] = (
                    df.loc[closed_bugs_idx, "closed_time"] - df.loc[closed_bugs_idx, "created_time"]).dt.days
        # 修复周期分类
        df["fix_duration_level"] = pd.cut(
            df["fix_duration"],
            bins=[0, 30, 90, 180, 365, float('inf')],
            labels=["短期(<30天)", "中期(30-90天)", "长期(90-180天)", "超长期(180-365天)", "极长期(>365天)"]
        )
    return df

def classify_commit_type(commit_msg):
    """提交类型分类（用于提交信息分析）"""
    if pd.isna(commit_msg):
        return "other"
    msg = commit_msg.lower()
    if "merge" in msg:
        return "merge"
    elif any(k in msg for k in ["fix", "bug", "issue", "error"]):
        return "bugfix"
    elif any(k in msg for k in ["feat", "feature", "add", "new"]):
        return "feature"
    elif any(k in msg for k in ["doc", "readme", "documentation"]):
        return "docs"
    elif any(k in msg for k in ["test", "unittest", "pytest"]):
        return "test"
    else:
        return "other"

# ========== 第一维度：历史提交信息分析统计 ==========
def analyze_commit_statistics(commit_df):
    """历史提交信息核心统计分析"""
    print("\n" + "=" * 50)
    print("【第一维度：历史提交信息分析统计】")
    print("=" * 50)

    if commit_df.empty:
        print("⚠️  无有效提交数据，跳过分析")
        return

    # 1. 基础规模统计
    print("\n1. 提交基础规模")
    print(f"   总提交数：{len(commit_df)}")
    print(
        f"   时间跨度：{commit_df['commit_time'].min().strftime('%Y-%m-%d')} 至 {commit_df['commit_time'].max().strftime('%Y-%m-%d')}")
    print(f"   平均单次提交修改文件数：{commit_df['files_changed'].mean():.2f}")
    print(f"   平均单次提交代码行数：{commit_df['total_changes'].mean():.2f}")
    print(f"   最大单次提交代码行数：{commit_df['total_changes'].max()}")

    # 2. 提交类型分布（反映迭代重心）
    print("\n2. 提交类型分布（迭代重心）")
    type_dist = commit_df["commit_type"].value_counts()
    for typ, count in type_dist.items():
        print(f"   {typ}：{count}次（{count / len(commit_df) * 100:.2f}%）")

    # 3. 核心贡献者分析（反映维护团队）
    print("\n3. 核心贡献者TOP5（维护团队）")
    contributor_dist = commit_df["author"].value_counts().head(5)
    for author, count in contributor_dist.items():
        fix_count = len(commit_df[(commit_df["author"] == author) & (commit_df["commit_type"] == "bugfix")])
        print(f"   {author}：{count}次提交（含{fix_count}次Bug修复）")

    # 4. 时间趋势分析（反映迭代节奏）
    print("\n4. 时间趋势分析（迭代节奏）")
    year_dist = commit_df["commit_year"].value_counts().sort_index()
    print("   年度提交分布：")
    for year, count in year_dist.items():
        print(f"     {int(year)}年：{count}次")

    # 5. 代码修改规模分析（反映开发精细化程度）
    print("\n5. 代码修改规模分布（开发精细化）")
    scale_dist = commit_df["change_scale"].value_counts()
    for scale, count in scale_dist.items():
        print(f"   {scale}：{count}次（{count / len(commit_df) * 100:.2f}%）")

# ========== 第二维度：Bug提交规律分析 ==========
def analyze_bug_rules(bug_df):
    """Bug提交规律核心分析"""
    print("\n" + "=" * 50)
    print("【第二维度：Bug提交规律分析】")
    print("=" * 50)

    if bug_df.empty:
        print("⚠️  无有效Bug数据，跳过分析")
        return

    bug_df = bug_df.dropna(subset=["state", "created_time"])

    # 1. Bug基础规模统计
    print("\n1. Bug基础规模")
    total_bugs = len(bug_df)
    closed_bugs = bug_df[bug_df["state"] == "closed"]
    open_bugs = bug_df[bug_df["state"] == "open"]
    print(f"   总Bug数：{total_bugs}")
    print(f"   已修复Bug：{len(closed_bugs)}（{len(closed_bugs) / total_bugs * 100:.2f}%）")
    print(f"   未修复Bug：{len(open_bugs)}（{len(open_bugs) / total_bugs * 100:.2f}%）")

    # 2. Bug提交时间规律（反映高发期）
    print("\n2. Bug提交时间规律（高发期）")
    year_dist = bug_df["created_year"].value_counts().sort_index()
    print("   年度Bug分布：")
    for year, count in year_dist.items():
        print(f"     {int(year)}年：{count}个（{count / total_bugs * 100:.2f}%）")

    # 3. Bug修复效率规律
    print("\n3. Bug修复效率规律")
    valid_closed_bugs = closed_bugs.dropna(subset=["fix_duration"])
    if len(valid_closed_bugs) > 0:
        print(f"   平均修复周期：{valid_closed_bugs['fix_duration'].mean():.2f}天")
        print(f"   中位数修复周期：{valid_closed_bugs['fix_duration'].median():.2f}天")
        print(f"   最长修复周期：{valid_closed_bugs['fix_duration'].max():.2f}天")

        # 修复周期分布
        duration_dist = valid_closed_bugs["fix_duration_level"].value_counts()
        print("\n   修复周期分布：")
        for level, count in duration_dist.items():
            print(f"     {level}：{count}个（{count / len(valid_closed_bugs) * 100:.2f}%）")

    # 4. Bug提交者规律（反映核心反馈用户）
    print("\n4. Bug提交者规律（核心反馈用户）")
    creator_dist = bug_df["creator"].value_counts().head(5)
    for creator, count in creator_dist.items():
        creator_closed = len(bug_df[(bug_df["creator"] == creator) & (bug_df["state"] == "closed")])
        print(f"   {creator}：提交{count}个Bug（{creator_closed}个已修复）")

    # 5. Bug讨论热度规律（反映问题关注度）
    print("\n5. Bug讨论热度规律（问题关注度）")
    avg_comments = bug_df["comments"].mean()
    max_comments_idx = bug_df["comments"].idxmax()
    print(f"   平均每个Bug讨论数：{avg_comments:.2f}条")
    print(f"   最高讨论度Bug：《{bug_df.loc[max_comments_idx, 'title']}》（{bug_df['comments'].max()}条评论）")

# ========== 可视化层（分维度生成图表） ==========
def visualize_analysis_results(commit_df, bug_df):
    """分维度生成可视化图表"""
    output_dir = "two_dimension_analysis_visuals"
    os.makedirs(output_dir, exist_ok=True)
    print(f"\n【可视化生成】图表将保存至：{output_dir}")

    # 加载中文字体属性（兜底，确保每个图表都能获取到中文字体）
    system = platform.system()
    if system == "Windows":
        font_prop = FontProperties(fname="C:/Windows/Fonts/simhei.ttf")  # 改用黑体，兼容性更好
    elif system == "macOS":
        font_prop = FontProperties(fname="/System/Library/Fonts/PingFang.ttc")
    else:
        font_prop = FontProperties(name="WenQuanYi Zen Hei")

    # 一、历史提交信息相关图表
    if not commit_df.empty:
        # 1. 提交类型分布饼图
        plt.figure(figsize=(8, 6))
        type_dist = commit_df["commit_type"].value_counts()
        colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7', '#DDA0DD']
        plt.pie(type_dist.values, labels=type_dist.index, autopct="%1.1f%%", startangle=90,
                colors=colors[:len(type_dist)])
        plt.title("历史提交类型分布", fontproperties=font_prop, fontsize=14, fontweight='bold')
        plt.savefig(f"{output_dir}/commit_type_dist.png", dpi=300, bbox_inches='tight')
        plt.close()

        # 2. 月度提交趋势图
        plt.figure(figsize=(12, 5))
        month_dist = commit_df["commit_month"].value_counts().sort_index()
        plt.bar(month_dist.index.astype(str), month_dist.values, color='#3498DB', alpha=0.8)
        plt.title("月度提交趋势", fontproperties=font_prop, fontsize=14, fontweight='bold')
        plt.xlabel("月份", fontproperties=font_prop, fontsize=12)
        plt.ylabel("提交次数", fontproperties=font_prop, fontsize=12)
        plt.xticks(rotation=45)
        plt.grid(axis='y', alpha=0.3)
        plt.tight_layout()
        plt.savefig(f"{output_dir}/commit_monthly_trend.png", dpi=300, bbox_inches='tight')
        plt.close()

        # 3. 核心贡献者TOP5柱状图
        plt.figure(figsize=(10, 6))
        contributor_dist = commit_df["author"].value_counts().head(5)
        plt.bar(contributor_dist.index, contributor_dist.values, color='#E74C3C', alpha=0.8)
        plt.title("核心贡献者TOP5", fontproperties=font_prop, fontsize=14, fontweight='bold')
        plt.xlabel("贡献者", fontproperties=font_prop, fontsize=12)
        plt.ylabel("提交次数", fontproperties=font_prop, fontsize=12)
        plt.xticks(rotation=45, ha='right')
        plt.grid(axis='y', alpha=0.3)
        plt.tight_layout()
        plt.savefig(f"{output_dir}/commit_contributor_top5.png", dpi=300, bbox_inches='tight')
        plt.close()

    # 二、Bug提交规律相关图表
    if not bug_df.empty:
        bug_df = bug_df.dropna(subset=["state", "created_time"])

        # 1. Bug状态分布饼图
        plt.figure(figsize=(8, 6))
        state_dist = bug_df["state"].value_counts()
        labels = ["已修复(closed)", "未修复(open)"] if set(state_dist.index) == {"open", "closed"} else state_dist.index
        plt.pie(state_dist.values, labels=labels, autopct="%1.1f%%", startangle=90, colors=['#2ECC71', '#E74C3C'])
        plt.title("Bug状态分布", fontproperties=font_prop, fontsize=14, fontweight='bold')
        plt.savefig(f"{output_dir}/bug_state_dist.png", dpi=300, bbox_inches='tight')
        plt.close()

        # 2. 年度Bug提交趋势图
        plt.figure(figsize=(10, 6))
        year_dist = bug_df["created_year"].value_counts().sort_index()
        plt.bar(year_dist.index.astype(int), year_dist.values, color='#9B59B6', alpha=0.8)
        plt.title("年度Bug提交趋势", fontproperties=font_prop, fontsize=14, fontweight='bold')
        plt.xlabel("年份", fontproperties=font_prop, fontsize=12)
        plt.ylabel("Bug数量", fontproperties=font_prop, fontsize=12)
        plt.grid(axis='y', alpha=0.3)
        plt.tight_layout()
        plt.savefig(f"{output_dir}/bug_yearly_trend.png", dpi=300, bbox_inches='tight')
        plt.close()

        # 3. Bug修复周期分布直方图
        valid_closed_bugs = bug_df.dropna(subset=["fix_duration"])
        if len(valid_closed_bugs) > 0:
            plt.figure(figsize=(10, 6))
            plt.hist(valid_closed_bugs["fix_duration"], bins=15, color='#F39C12', alpha=0.7, edgecolor='black')
            mean_duration = valid_closed_bugs["fix_duration"].mean()
            # 图例使用fontproperties
            plt.axvline(mean_duration, color='red', linestyle='--',
                        label=f'平均值：{mean_duration:.0f}天', fontproperties=font_prop)
            plt.title("Bug修复周期分布", fontproperties=font_prop, fontsize=14, fontweight='bold')
            plt.xlabel("修复周期（天）", fontproperties=font_prop, fontsize=12)
            plt.ylabel("Bug数量", fontproperties=font_prop, fontsize=12)
            plt.legend(prop=font_prop)
            plt.grid(alpha=0.3)
            plt.tight_layout()
            plt.savefig(f"{output_dir}/bug_fix_duration_dist.png", dpi=300, bbox_inches='tight')
            plt.close()

    print("✅  所有图表生成完成！")

# ========== 数据保存 ==========
def save_analysis_data(commit_df, bug_df):
    """保存分析数据至CSV，便于后续深度分析"""
    commit_df.to_csv("commit_statistics_data.csv", index=False, encoding="utf-8-sig")
    bug_df.to_csv("bug_rules_data.csv", index=False, encoding="utf-8-sig")
    print("\n✅  分析数据已保存：")
    print("   - commit_statistics_data.csv：历史提交信息完整数据")
    print("   - bug_rules_data.csv：Bug提交规律完整数据")

# ========== 主函数 ==========
if __name__ == "__main__":
    # 1. 拉取数据
    commit_df = fetch_commits_data()
    bug_df = fetch_bugs_data()

    # 2. 双维度分析
    analyze_commit_statistics(commit_df)
    analyze_bug_rules(bug_df)

    # 3. 可视化与数据保存
    visualize_analysis_results(commit_df, bug_df)
    save_analysis_data(commit_df, bug_df)

    print("\n" + "=" * 50)
    print("【双维度分析完成！】")
    print("核心输出：")
    print(f"1. 分析报告：控制台已打印（提交统计 + Bug规律）")
    print(f"2. 可视化图表：two_dimension_analysis_visuals 目录")
    print(f"3. 原始数据：commit_statistics_data.csv + bug_rules_data.csv")
    print("=" * 50)