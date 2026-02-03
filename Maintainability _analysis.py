import xml.etree.ElementTree as ET
import re
from typing import List, Optional, Dict, Final
from pathlib import Path
# 配置常量 - 便于统一维护和修改
SCORE_DEDUCTIONS: Final[Dict[str, int]] = {
    "file_not_found": 50,
    "xml_parse_error": 80,
    "unknown_load_error": 30,
    "invalid_version_format": 10,
    "sdk_special_chars": 15,
    "duplicate_component": 20,
    "python_version_too_low": 10
}


# 版本常量
MIN_SUPPORTED_PYTHON_VERSION: Final[float] = 3.8

# 正则常量
VERSION_PATTERN: Final[str] = r"^\d+(\.\d+)?$"
SPECIAL_CHAR_PATTERN: Final[str] = r"[^\w\s\(\)]"
PYTHON_VERSION_PATTERN: Final[str] = r"Python (\d+\.\d+)"


class XMLMaintainabilityAnalyzer:
    """
    XML配置文件可维护性分析器
    用于分析XML配置文件（如IDE的misc.xml）的可维护性，包含以下核心能力：
    1. XML文件加载与基础异常处理
    2. 配置规范性检查（版本格式、SDK命名）
    3. 重复配置项检测
    4. Python SDK版本兼容性校验
    5. 可维护性得分计算与可视化报告生成
    """

    def __init__(self, file_path: str):
        """
        初始化分析器
        
        Args:
            file_path: 待分析的XML文件路径（支持绝对/相对路径）
        """
        self.file_path: str = file_path
        self.tree: Optional[ET.ElementTree] = None
        self.root: Optional[ET.Element] = None
        self.issues: List[str] = []  # 存储检测到的可维护性问题
        self.readability_score: int = 100  # 初始可读性满分100分
        
        # 初始化时自动加载XML文件
        self.load_xml()

    def load_xml(self) -> None:
        """
        加载并解析XML文件，捕获常见异常并记录问题、扣减对应分数
        异常类型：
        - FileNotFoundError: 文件不存在
        - ET.ParseError: XML语法错误
        - Exception: 其他未知加载错误
        """
        # 先校验路径格式
        file = Path(self.file_path)
        if not file.suffix.lower() == ".xml":
            self.issues.append(f"[警告] 文件不是XML格式: {self.file_path}")
            self.readability_score -= 10

        try:
            self.tree = ET.parse(self.file_path)
            self.root = self.tree.getroot()
        except FileNotFoundError:
            error_msg = f"[严重] 文件不存在: {self.file_path}"
            self.issues.append(error_msg)
            self.readability_score -= SCORE_DEDUCTIONS["file_not_found"]
        except ET.ParseError as e:
            error_msg = f"[严重] XML语法错误: {str(e)}"
            self.issues.append(error_msg)
            self.readability_score -= SCORE_DEDUCTIONS["xml_parse_error"]
        except Exception as e:
            error_msg = f"[未知] 文件加载失败: {str(e)}"
            self.issues.append(error_msg)
            self.readability_score -= SCORE_DEDUCTIONS["unknown_load_error"]

        # 确保分数不会低于0
        self.readability_score = max(0, self.readability_score)

    def check_config_norm(self) -> List[str]:
        """
        检查配置规范性：
        1. project根节点版本格式（纯数字/数字+小数点）
        2. Python SDK名称（避免特殊字符）
        
        Returns:
            规范性问题列表
        """
        norm_issues: List[str] = []
        if not self.root:
            return norm_issues

        # 1. 检查project版本格式
        project_version = self.root.get("version")
        if project_version:
            if not re.match(VERSION_PATTERN, project_version):
                issue = (
                    f"[规范] project版本格式不规范: {project_version} "
                    f"（建议：纯数字/数字+小数点，如3.8、4）"
                )
                norm_issues.append(issue)
                self.readability_score -= SCORE_DEDUCTIONS["invalid_version_format"]

        # 2. 检查Python SDK命名规范性
        for component in self.root.findall("component"):
            comp_name = component.get("name")
            if comp_name == "ProjectRootManager":
                jdk_option = component.find("option[@name='project-jdk-name']")
                if jdk_option:
                    jdk_val = jdk_option.get("value")
                    if jdk_val and re.search(SPECIAL_CHAR_PATTERN, jdk_val):
                        issue = (
                            f"[规范] Python SDK名称含特殊字符: {jdk_val} "
                            f"（易导致解析异常，建议仅使用字母/数字/空格/括号）"
                        )
                        norm_issues.append(issue)
                        self.readability_score -= SCORE_DEDUCTIONS["sdk_special_chars"]

        self.readability_score = max(0, self.readability_score)
        return norm_issues

    def detect_duplicate_config(self) -> List[str]:
        """
        检测重复的component配置项（重复配置会降低可维护性，易引发冲突）
        
        Returns:
            重复配置问题列表
        """
        duplicate_issues: List[str] = []
        if not self.root:
            return duplicate_issues

        component_names: List[str] = []
        for component in self.root.findall("component"):
            comp_name = component.get("name")
            if not comp_name:
                duplicate_issues.append("[规范] 存在无名称的component配置项（建议补充名称）")
                self.readability_score -= 10
                continue

            if comp_name in component_names:
                issue = f"[重复] 存在重复的component配置: {comp_name}（建议合并相同名称的配置项）"
                duplicate_issues.append(issue)
                self.readability_score -= SCORE_DEDUCTIONS["duplicate_component"]
            else:
                component_names.append(comp_name)

        self.readability_score = max(0, self.readability_score)
        return duplicate_issues

    def check_version_compatibility(self) -> List[str]:
        """
        检查Python SDK版本兼容性（验证是否为当前主流支持版本）
        
        Returns:
            版本兼容问题列表
        """
        compat_issues: List[str] = []
        if not self.root:
            return compat_issues

        for component in self.root.findall("component"):
            if component.get("name") == "ProjectRootManager":
                jdk_option = component.find("option[@name='project-jdk-name']")
                if jdk_option:
                    jdk_val = jdk_option.get("value")
                    if jdk_val and "Python" in jdk_val:
                        version_match = re.search(PYTHON_VERSION_PATTERN, jdk_val)
                        if version_match:
                            try:
                                python_version = float(version_match.group(1))
                                if python_version < MIN_SUPPORTED_PYTHON_VERSION:
                                    issue = (
                                        f"[兼容] Python版本{python_version}过低 "
                                        f"（建议升级至{MIN_SUPPORTED_PYTHON_VERSION}+，减少长期维护成本）"
                                    )
                                    compat_issues.append(issue)
                                    self.readability_score -= SCORE_DEDUCTIONS["python_version_too_low"]
                            except ValueError:
                                issue = f"[兼容] 无法解析Python版本号: {jdk_val}（建议检查SDK配置）"
                                compat_issues.append(issue)
                                self.readability_score -= 10

        self.readability_score = max(0, self.readability_score)
        return compat_issues

    def calculate_maintainability_score(self) -> int:
        """
        计算整体可维护性得分（确保分数在0-100之间）
        
        Returns:
            最终可维护性得分（0-100）
        """
        return max(0, min(self.readability_score, 100))

    def get_maintainability_grade(self) -> str:
        """
        根据得分判定可维护性等级
        
        Returns:
            等级描述（优秀/良好/一般/较差）
        """
        score = self.calculate_maintainability_score()
        if score >= 90:
            return "优秀"
        elif score >= 70:
            return "良好"
        elif score >= 50:
            return "一般"
        else:
            return "较差"

    def generate_report(self) -> str:
        """
        生成结构化、可视化的可维护性分析报告
        
        Returns:
            格式化的分析报告字符串
        """
        # 收集所有检测问题
        norm_issues = self.check_config_norm()
        duplicate_issues = self.detect_duplicate_config()
        compat_issues = self.check_version_compatibility()
        self.issues.extend(norm_issues + duplicate_issues + compat_issues)

        # 构建报告内容
        report_parts = [
            "# XML配置文件可维护性分析报告",
            f"## 文件路径: {Path(self.file_path).resolve()}",  # 显示绝对路径
            f"## 整体可维护性得分: {self.calculate_maintainability_score()}/100",
            "\n### 一、问题明细"
        ]

        # 添加问题列表
        if self.issues:
            for idx, issue in enumerate(self.issues, 1):
                report_parts.append(f"{idx}. {issue}")
        else:
            report_parts.append("✅ 未检测到任何可维护性问题")

        # 添加优化建议
        report_parts.extend([
            "\n### 二、优化建议",
            "1. 配置规范性：统一版本格式（纯数字/小数点）、SDK名称仅使用字母/数字/空格/括号",
            "2. 重复配置：合并重复的component节点，删除冗余配置",
            f"3. 版本兼容：升级Python至{MIN_SUPPORTED_PYTHON_VERSION}+，使用长期支持版本",
            "4. 可读性：保持XML缩进统一、节点命名语义化、添加必要注释"
        ])

        # 添加等级评定
        report_parts.extend([
            "\n### 三、可维护性等级",
            f"当前文件可维护性等级：{self.get_maintainability_grade()}（得分{self.calculate_maintainability_score()}）"
        ])

        # 拼接报告（统一换行格式）
        return "\n".join(report_parts)


# ---------------------- 执行分析 ----------------------
if __name__ == "__main__":
    # 使用示例 - 替换为实际的XML文件路径
    XML_FILE_PATH = "OSS/.idea/misc.xml"
    
    # 初始化分析器并生成报告
    try:
        analyzer = XMLMaintainabilityAnalyzer(XML_FILE_PATH)
        report = analyzer.generate_report()
        print(report)
        
        # 可选：将报告保存到文件
        with open("xml_maintainability_report.md", "w", encoding="utf-8") as f:
            f.write(report)
        print("\n📄 报告已保存至: xml_maintainability_report.md")
    except Exception as e:
        print(f"❌ 分析执行失败: {str(e)}")


