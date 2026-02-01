#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
requests 静态分析完整脚本（含可视化）
核心功能：
1. 基础层：模块依赖、函数列表、代码规模/粒度、命名规范
2. 合规层：PEP8编码规范检查（集成flake8）
3. 质量层：代码复杂度量化（集成radon，修复格式解析问题）
4. 安全层：基础安全漏洞检测（集成bandit）
5. 可视化层：自动生成4类核心图表，保存为图片文件
输出：控制台+JSON报告+可视化图片，结果可直接用于静态分析报告
前置依赖：pip install requests==2.31.0 flake8 radon bandit matplotlib seaborn wordcloud numpy
"""
import ast
import os
import sys
import json
import re
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from wordcloud import WordCloud
from importlib import import_module
from subprocess import run, PIPE, CalledProcessError

# 设置中文字体（避免乱码）
plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

# ===================== 基础配置 =====================
# 输出路径
REPORT_PATH = "requests_static_analysis_report.json"
VISUAL_PATH = "requests_visual_report"  # 可视化图片保存目录
# 核心模块列表
CORE_MODULES = [
    "sessions.py", "models.py", "api.py", "adapters.py", "exceptions.py"
]
# 忽略的flake8检查项（可根据需求调整）
FLAKE8_IGNORE = "E501,W503"  # 忽略行超长、换行位置警告


# ===================== 基础层分析：依赖/函数/代码规模 =====================
def get_requests_core_modules():
    """自动定位requests核心模块文件路径"""
    try:
        requests_module = import_module("requests")
        requests_path = os.path.dirname(requests_module.__file__)
    except ImportError:
        print("❌ 未检测到requests库，请先执行：pip install requests==2.31.0")
        sys.exit(1)

    core_modules = []
    for module_name in CORE_MODULES:
        module_path = os.path.join(requests_path, module_name)
        if os.path.exists(module_path):
            core_modules.append({
                "name": module_name,
                "path": module_path,
                "dir": requests_path
            })
        else:
            print(f"⚠️  版本差异：未找到{module_name}，已跳过")

    if not core_modules:
        print("❌ 未找到任何核心模块，脚本终止")
        sys.exit(1)
    return core_modules


def parse_module_dependencies_and_functions(module_info):
    """解析模块依赖、函数列表、代码规模"""
    module_path = module_info["path"]
    module_name = module_info["name"]

    # 初始化结果
    result = {
        "dependencies": {"internal": [], "external": []},
        "functions": [],
        "code_size": {"total_lines": 0, "non_blank_lines": 0, "func_count": 0},
        "naming_issues": []
    }

    # 读取源码
    with open(module_path, "r", encoding="utf-8") as f:
        source_code = f.read()
    with open(module_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # 1. 代码规模统计
    result["code_size"]["total_lines"] = len(lines)
    # 过滤空行/单行注释
    non_blank = [l for l in lines if l.strip() and not l.strip().startswith("#")]
    result["code_size"]["non_blank_lines"] = len(non_blank)

    # 2. 解析AST提取依赖和函数
    try:
        tree = ast.parse(source_code)
    except SyntaxError as e:
        print(f"❌ 解析{module_name}失败：{str(e)}")
        return result

    func_names = []
    for node in ast.walk(tree):
        # 提取依赖
        if isinstance(node, ast.Import):
            for alias in node.names:
                dep = alias.name.split(".")[0]
                if dep not in result["dependencies"]["external"]:
                    result["dependencies"]["external"].append(dep)
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            if node.module.startswith("."):
                dep = node.module.lstrip(".")
                if dep and dep not in result["dependencies"]["internal"]:
                    result["dependencies"]["internal"].append(dep)
            else:
                dep = node.module.split(".")[0]
                if dep not in result["dependencies"]["external"]:
                    result["dependencies"]["external"].append(dep)

        # 提取函数
        if isinstance(node, ast.FunctionDef):
            func_names.append(node.name)
            result["functions"].append({
                "name": node.name,
                "line_no": node.lineno,
                "is_class_method": False,
                "type": "普通函数"
            })
        elif isinstance(node, ast.AsyncFunctionDef):
            func_names.append(node.name)
            result["functions"].append({
                "name": node.name,
                "line_no": node.lineno,
                "is_class_method": False,
                "type": "异步函数"
            })
        elif isinstance(node, ast.ClassDef):
            # 检查类名命名规范（大驼峰）
            if not node.name[0].isupper() or not node.name.isidentifier():
                result["naming_issues"].append(f"类名{node.name}不符合大驼峰规范")
            # 提取类方法
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    func_names.append(item.name)
                    result["functions"].append({
                        "name": item.name,
                        "line_no": item.lineno,
                        "is_class_method": True,
                        "type": "类方法"
                    })

    # 3. 命名规范检查（函数名：小写+下划线）
    for name in func_names:
        if name.startswith("__") and name.endswith("__"):
            continue  # 跳过魔法方法
        if not name.islower() or " " in name or "-" in name:
            result["naming_issues"].append(f"函数名{name}不符合小写+下划线规范")

    # 去重+排序
    result["dependencies"]["internal"] = sorted(set(result["dependencies"]["internal"]))
    result["dependencies"]["external"] = sorted(set(result["dependencies"]["external"]))
    result["functions"] = sorted(result["functions"], key=lambda x: x["line_no"])
    result["code_size"]["func_count"] = len(result["functions"])

    return result


# ===================== 合规层分析：PEP8规范检查 =====================
def check_pep8_compliance(module_info):
    """使用flake8检查PEP8合规性"""
    module_path = module_info["path"]
    module_name = module_info["name"]

    try:
        # 执行flake8检查
        result = run(
            ["flake8", f"--ignore={FLAKE8_IGNORE}", module_path],
            stdout=PIPE, stderr=PIPE, encoding="utf-8"
        )
        issues = result.stdout.strip().split("\n") if result.stdout else []
        # 过滤空行
        issues = [i for i in issues if i.strip()]

        return {
            "total_issues": len(issues),
            "issues": issues,
            "severity": "低" if len(issues) < 5 else "中" if len(issues) < 20 else "高"
        }
    except (CalledProcessError, FileNotFoundError):
        print(f"⚠️  未安装flake8或执行失败，跳过{module_name}的PEP8检查")
        return {"total_issues": -1, "issues": [], "severity": "未知"}


# ===================== 质量层分析：代码复杂度（修复解析逻辑） =====================
def check_code_complexity(module_info):
    """使用radon检查代码复杂度（圈复杂度），修复格式解析问题"""
    module_path = module_info["path"]
    module_name = module_info["name"]

    try:
        # 圈复杂度分析（-s：显示简单格式，减少解析难度）
        cc_result = run(
            ["radon", "cc", "-s", "-n", "A", module_path],  # -n A：显示所有复杂度等级
            stdout=PIPE, stderr=PIPE, encoding="utf-8"
        )
        # 行数统计
        sloc_result = run(
            ["radon", "sloc", module_path],
            stdout=PIPE, stderr=PIPE, encoding="utf-8"
        )

        # 解析复杂度结果（核心修复：兼容多种格式）
        cc_issues = []
        if cc_result.stdout:
            # 正则提取数字复杂度值（匹配纯数字或括号内的数字）
            complexity_pattern = re.compile(r'(\d+)')
            for line in cc_result.stdout.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue

                # 提取函数名（冒号/空格分割）
                func_name = "未知函数"
                # 分割行内容，提取函数名部分
                parts = re.split(r'[:\s()-]+', line)
                # 过滤空字符串
                parts = [p for p in parts if p.strip()]

                # 提取复杂度值（优先找纯数字）
                complexity = 0
                for part in parts:
                    if part.isdigit():
                        complexity = int(part)
                        break

                # 提取函数名（找合理的标识符）
                for part in parts:
                    if part.isidentifier() and part not in ["A", "B", "C", "D", "F"]:  # 排除复杂度等级
                        func_name = part
                        break

                if complexity > 0:
                    cc_issues.append({
                        "function": func_name,
                        "complexity": complexity,
                        "risk": "低" if complexity < 10 else "中" if complexity < 20 else "高"
                    })

        # 解析行数统计
        sloc_data = {}
        if sloc_result.stdout:
            for line in sloc_result.stdout.strip().split("\n"):
                if ":" in line:
                    key, value = line.split(":", 1)
                    sloc_data[key.strip().lower()] = value.strip()

        # 计算最大复杂度
        max_complexity = max([i["complexity"] for i in cc_issues], default=0)
        # 风险等级
        complexity_risk = "低" if max_complexity < 10 else "中" if max_complexity < 20 else "高"

        return {
            "cyclomatic_complexity": cc_issues,
            "max_complexity": max_complexity,
            "sloc": sloc_data,
            "complexity_risk": complexity_risk
        }
    except (CalledProcessError, FileNotFoundError):
        print(f"⚠️  未安装radon或执行失败，跳过{module_name}的复杂度检查")
        return {"cyclomatic_complexity": [], "max_complexity": 0, "sloc": {}, "complexity_risk": "未知"}
    except Exception as e:
        print(f"⚠️  解析{module_name}复杂度失败：{str(e)}，跳过该模块复杂度检查")
        return {"cyclomatic_complexity": [], "max_complexity": 0, "sloc": {}, "complexity_risk": "未知"}


# ===================== 安全层分析：基础安全检测 =====================
def check_security_issues(module_info):
    """使用bandit做基础安全检测"""
    module_path = module_info["path"]
    module_name = module_info["name"]

    try:
        result = run(
            ["bandit", "-r", "-f", "json", module_path],
            stdout=PIPE, stderr=PIPE, encoding="utf-8"
        )
        if not result.stdout:
            return {"total_issues": 0, "issues": [], "risk": "低"}

        bandit_data = json.loads(result.stdout)
        issues = []
        for issue in bandit_data.get("results", []):
            issues.append({
                "line_no": issue["line_number"],
                "severity": issue["issue_severity"],
                "confidence": issue["issue_confidence"],
                "description": issue["issue_text"]
            })

        return {
            "total_issues": len(issues),
            "issues": issues,
            "risk": "低" if len(issues) == 0 else "中" if len(issues) < 3 else "高"
        }
    except (CalledProcessError, FileNotFoundError, json.JSONDecodeError):
        print(f"⚠️  未安装bandit或执行失败，跳过{module_name}的安全检查")
        return {"total_issues": -1, "issues": [], "risk": "未知"}
    except Exception as e:
        print(f"⚠️  解析{module_name}安全检测结果失败：{str(e)}，跳过该模块安全检查")
        return {"total_issues": -1, "issues": [], "risk": "未知"}


# ===================== 可视化层：生成核心图表 =====================
def init_visual_dir():
    """初始化可视化目录"""
    if not os.path.exists(VISUAL_PATH):
        os.makedirs(VISUAL_PATH)
    return VISUAL_PATH


def plot_module_size(report):
    """1. 核心模块规模对比图（柱状图）"""
    modules = list(report["modules"].keys())
    total_lines = [report["modules"][m]["basic"]["code_size"]["total_lines"] for m in modules]
    non_blank_lines = [report["modules"][m]["basic"]["code_size"]["non_blank_lines"] for m in modules]
    func_counts = [report["modules"][m]["basic"]["code_size"]["func_count"] for m in modules]

    # 绘图
    fig, ax = plt.subplots(figsize=(12, 7))
    x = np.arange(len(modules))
    width = 0.25

    # 绘制三组柱状图
    rects1 = ax.bar(x - width, total_lines, width, label='总行数', color='#3498db')
    rects2 = ax.bar(x, non_blank_lines, width, label='有效行数', color='#2ecc71')
    rects3 = ax.bar(x + width, func_counts, width, label='函数总数', color='#e74c3c')

    # 添加标签和标题
    ax.set_xlabel('核心模块', fontsize=12)
    ax.set_ylabel('数量', fontsize=12)
    ax.set_title('Requests核心模块规模对比', fontsize=14, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(modules, rotation=15)
    ax.legend()

    # 标注数值
    def autolabel(rects):
        for rect in rects:
            height = rect.get_height()
            ax.annotate(f'{height}',
                        xy=(rect.get_x() + rect.get_width() / 2, height),
                        xytext=(0, 3),
                        textcoords="offset points",
                        ha='center', va='bottom', fontsize=9)

    autolabel(rects1)
    autolabel(rects2)
    autolabel(rects3)

    # 保存图片
    plt.tight_layout()
    save_path = os.path.join(init_visual_dir(), "module_size.png")
    plt.savefig(save_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"✅ 模块规模对比图已保存至：{save_path}")


def plot_complexity(report):
    """2. 核心模块圈复杂度对比图（带阈值线）"""
    modules = list(report["modules"].keys())
    max_complexity = [report["modules"][m]["complexity"]["max_complexity"] for m in modules]
    threshold = [20] * len(modules)  # 行业高风险阈值

    # 绘图
    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.bar(modules, max_complexity, color=['#e74c3c', '#e67e22', '#f39c12', '#f1c40f', '#9b59b6'])

    # 绘制阈值线
    ax.plot(modules, threshold, 'r--', label='高风险阈值（20）', linewidth=2)

    # 添加标签和标题
    ax.set_xlabel('核心模块', fontsize=12)
    ax.set_ylabel('圈复杂度', fontsize=12)
    ax.set_title('Requests核心模块圈复杂度对比', fontsize=14, fontweight='bold')
    ax.set_xticklabels(modules, rotation=15)
    ax.legend()

    # 标注数值
    for bar in bars:
        height = bar.get_height()
        ax.annotate(f'{height}',
                    xy=(bar.get_x() + bar.get_width() / 2, height),
                    xytext=(0, 3),
                    textcoords="offset points",
                    ha='center', va='bottom', fontsize=10)

    # 保存图片
    plt.tight_layout()
    save_path = os.path.join(init_visual_dir(), "complexity.png")
    plt.savefig(save_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"✅ 圈复杂度对比图已保存至：{save_path}")


def plot_risk_radar(report):
    """3. 整体风险雷达图"""
    # 风险等级量化：低=1，中=2，高=3
    risk_mapping = {"低": 1, "中": 2, "高": 3, "未知": 0}

    # 提取各模块的风险维度数据
    modules = list(report["modules"].keys())
    dimensions = ['编码规范', '命名规范', '复杂度', '安全']
    angles = np.linspace(0, 2 * np.pi, len(dimensions), endpoint=False).tolist()
    angles += angles[:1]  # 闭合雷达图

    # 计算整体风险均值（用于雷达图）
    pep8_risk = []
    naming_risk = []
    complexity_risk = []
    security_risk = []

    for m in modules:
        # 编码规范风险
        pep8_severity = report["modules"][m]["pep8"]["severity"]
        pep8_risk.append(risk_mapping[pep8_severity] if pep8_severity != "未知" else 1)

        # 命名规范风险（0个问题=低，≥1=中）
        naming_issues = len(report["modules"][m]["basic"]["naming_issues"])
        naming_risk.append(1 if naming_issues == 0 else 2)

        # 复杂度风险
        comp_severity = report["modules"][m]["complexity"]["complexity_risk"]
        complexity_risk.append(risk_mapping[comp_severity] if comp_severity != "未知" else 3)

        # 安全风险
        sec_risk = report["modules"][m]["security"]["risk"]
        security_risk.append(risk_mapping[sec_risk] if sec_risk != "未知" else 1)

    # 计算均值
    avg_pep8 = np.mean(pep8_risk)
    avg_naming = np.mean(naming_risk)
    avg_complexity = np.mean(complexity_risk)
    avg_security = np.mean(security_risk)

    # 准备雷达图数据
    values = [avg_pep8, avg_naming, avg_complexity, avg_security]
    values += values[:1]  # 闭合

    # 绘图
    fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))
    ax.plot(angles, values, 'o-', linewidth=2, color='#e74c3c', label='整体风险均值')
    ax.fill(angles, values, alpha=0.25, color='#e74c3c')

    # 设置刻度和标签
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(dimensions, fontsize=12)
    ax.set_ylim(0, 3)
    ax.set_yticks([1, 2, 3])
    ax.set_yticklabels(['低', '中', '高'], fontsize=10)
    ax.set_title('Requests库整体风险维度雷达图', fontsize=14, fontweight='bold', pad=20)
    ax.legend(loc='upper right')

    # 保存图片
    plt.tight_layout()
    save_path = os.path.join(init_visual_dir(), "risk_radar.png")
    plt.savefig(save_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"✅ 风险雷达图已保存至：{save_path}")


def plot_dependency_wordcloud(report):
    """4. 外部依赖词云图"""
    # 收集所有外部依赖
    all_deps = []
    for m in report["modules"].keys():
        deps = report["modules"][m]["basic"]["dependencies"]["external"]
        all_deps.extend(deps)

    # 过滤空依赖
    all_deps = [d for d in all_deps if d]
    if not all_deps:
        print("⚠️  无外部依赖数据，跳过词云图生成")
        return

    # 生成词云文本
    dep_text = ' '.join(all_deps)

    # 生成词云
    wordcloud = WordCloud(
        width=800, height=600,
        background_color='white',
        max_words=50,
        font_path='simhei.ttf' if os.path.exists('simhei.ttf') else None,
        colormap='viridis'
    ).generate(dep_text)

    # 绘图并保存
    fig, ax = plt.subplots(figsize=(10, 7))
    ax.imshow(wordcloud, interpolation='bilinear')
    ax.axis('off')
    ax.set_title('Requests核心模块外部依赖词云', fontsize=14, fontweight='bold', pad=20)

    # 保存图片
    save_path = os.path.join(init_visual_dir(), "dependency_wordcloud.png")
    plt.savefig(save_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"✅ 外部依赖词云图已保存至：{save_path}")


def generate_visual_report(report):
    """生成所有可视化图表"""
    print("\n📊 开始生成可视化报告...")
    plot_module_size(report)
    plot_complexity(report)
    plot_risk_radar(report)
    plot_dependency_wordcloud(report)
    print(f"\n✅ 所有可视化图表已保存至目录：{VISUAL_PATH}")


# ===================== 结果整合与输出 =====================
def generate_analysis_report(core_modules):
    """整合所有分析结果，生成报告"""
    final_report = {
        "summary": {
            "total_modules": len(core_modules),
            "analyzed_modules": [],
            "overall_risk": "低"
        },
        "modules": {}
    }

    # 逐个模块分析
    for module in core_modules:
        module_name = module["name"]
        print(f"\n🔍 正在分析模块：{module_name}")

        # 基础层分析
        basic_analysis = parse_module_dependencies_and_functions(module)
        # 合规层分析
        pep8_analysis = check_pep8_compliance(module)
        # 质量层分析
        complexity_analysis = check_code_complexity(module)
        # 安全层分析
        security_analysis = check_security_issues(module)

        # 整合模块结果
        final_report["modules"][module_name] = {
            "path": module["path"],
            "basic": basic_analysis,
            "pep8": pep8_analysis,
            "complexity": complexity_analysis,
            "security": security_analysis
        }
        final_report["summary"]["analyzed_modules"].append(module_name)

    # 整体风险评估
    total_high_risk = 0
    for mod_data in final_report["modules"].values():
        if mod_data["pep8"]["severity"] == "高" or mod_data["complexity"]["complexity_risk"] == "高" or \
                mod_data["security"]["risk"] == "高":
            total_high_risk += 1
    final_report["summary"]["overall_risk"] = "高" if total_high_risk >= 2 else "中" if total_high_risk >= 1 else "低"

    # 输出到控制台
    print_report_console(final_report)
    # 保存到文件
    save_report_file(final_report)
    # 生成可视化报告
    generate_visual_report(final_report)

    return final_report


def print_report_console(report):
    """控制台格式化输出"""
    print("\n" + "=" * 100)
    print("📋 requests 静态分析完整报告（控制台版）")
    print("=" * 100)

    # 汇总信息
    print(f"\n【汇总信息】")
    print(f"  分析模块数：{report['summary']['total_modules']}")
    print(f"  分析模块：{', '.join(report['summary']['analyzed_modules'])}")
    print(f"  整体风险等级：{report['summary']['overall_risk']}")

    # 模块详情
    for mod_name, mod_data in report["modules"].items():
        print(f"\n【模块：{mod_name}】")
        print(f"  路径：{mod_data['path']}")

        # 基础信息
        print(f"  📌 基础信息：")
        print(
            f"     总行数：{mod_data['basic']['code_size']['total_lines']} | 有效行数：{mod_data['basic']['code_size']['non_blank_lines']} | 函数总数：{mod_data['basic']['code_size']['func_count']}")
        print(
            f"     内部依赖：{', '.join(mod_data['basic']['dependencies']['internal']) if mod_data['basic']['dependencies']['internal'] else '无'}")
        print(
            f"     外部依赖：{', '.join(mod_data['basic']['dependencies']['external']) if mod_data['basic']['dependencies']['external'] else '无'}")
        print(
            f"     命名规范问题：{len(mod_data['basic']['naming_issues'])}个 | {', '.join(mod_data['basic']['naming_issues']) if mod_data['basic']['naming_issues'] else '无'}")

        # PEP8合规性
        print(f"  📌 PEP8合规性：")
        if mod_data['pep8']['total_issues'] == -1:
            print(f"     问题总数：未检测 | 风险等级：未知")
        else:
            print(f"     问题总数：{mod_data['pep8']['total_issues']} | 风险等级：{mod_data['pep8']['severity']}")

        # 复杂度
        print(f"  📌 代码复杂度：")
        print(
            f"     最高圈复杂度：{mod_data['complexity']['max_complexity']} | 风险等级：{mod_data['complexity']['complexity_risk']}")

        # 安全
        print(f"  📌 安全检测：")
        if mod_data['security']['total_issues'] == -1:
            print(f"     问题总数：未检测 | 风险等级：未知")
        else:
            print(f"     问题总数：{mod_data['security']['total_issues']} | 风险等级：{mod_data['security']['risk']}")

        print("-" * 100)

    print(f"\n✅ 分析完成！详细报告已保存至：{REPORT_PATH}")


def save_report_file(report):
    """保存报告到JSON文件"""
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=4)


# ===================== 主执行流程 =====================
if __name__ == "__main__":
    # 1. 检查依赖（友好提示）
    required_tools = ["flake8", "radon", "bandit"]
    missing_tools = []
    for tool in required_tools:
        try:
            run([tool, "--version"], stdout=PIPE, stderr=PIPE)
        except FileNotFoundError:
            missing_tools.append(tool)
    if missing_tools:
        print(f"⚠️  缺少必要工具：{', '.join(missing_tools)}，请执行：pip install {' '.join(missing_tools)}")
        print("   （缺少工具仅会跳过对应分析，基础分析仍可执行）")

    # 2. 定位核心模块
    core_modules = get_requests_core_modules()

    # 3. 生成分析报告
    generate_analysis_report(core_modules)