import xml.etree.ElementTree as ET
import re
from typing import List, Optional, Dict, Final, Tuple
from pathlib import Path
from dataclasses import dataclass

# ===================== 配置常量（优化：分类整理+补充魔法值常量） =====================
@dataclass(frozen=True)  # 用数据类管理扣分规则，更易扩展
class ScoreDeduction:
    """可维护性扣分规则常量"""
    FILE_NOT_FOUND: int = 50
    XML_PARSE_ERROR: int = 80
    UNKNOWN_LOAD_ERROR: int = 30
    INVALID_VERSION_FORMAT: int = 10
    SDK_SPECIAL_CHARS: int = 15
    DUPLICATE_COMPONENT: int = 20
    PYTHON_VERSION_TOO_LOW: int = 10
    EMPTY_COMPONENT_NAME: int = 10  # 补充原魔法值10的常量
    INVALID_PYTHON_VERSION_PARSE: int = 10  # 补充原魔法值10的常量
    NON_XML_FILE: int = 10  # 补充原魔法值10的常量

# 版本常量
MIN_SUPPORTED_PYTHON_VERSION: Final[float] = 3.8

# 正则常量（优化：预编译正则，提升匹配性能）
VERSION_PATTERN: Final[re.Pattern] = re.compile(r"^\d+(\.\d+)?$")
SPECIAL_CHAR_PATTERN: Final[re.Pattern] = re.compile(r"[^\w\s\(\)]")
PYTHON_VERSION_PATTERN: Final[re.Pattern] = re.compile(r"Python (\d+\.\d+)")

# 可维护性等级映射（优化：抽离成常量，便于修改等级规则）
MAINTAINABILITY_GRADES: Final[List[Tuple[int, str]]] = [
    (90, "优秀"),
    (70, "良好"),
    (50, "一般"),
    (0, "较差")
]

# ===================== 核心分析类（优化：职责拆分+代码简化+鲁棒性增强） =====================
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

    def __init__(self, file_path: str | Path):
        """
        初始化分析器
        
        Args:
            file_path: 待分析的XML文件路径（支持字符串/Path对象）
        """
        self.file_path: Path = Path(file_path).resolve()  # 统一为绝对路径
        self.tree: Optional[ET.ElementTree] = None
        self.root: Optional[ET.Element] = None
        self.issues: List[str] = []  # 存储检测到的可维护性问题
        self.readability_score: int = 100  # 初始可读性满分100分
        
        # 初始化时自动加载XML文件
        self.load_xml()

    def _clamp_score(self) -> None:
        """辅助函数：确保分数不低于0、不高于100（抽离重复逻辑）"""
        self.readability_score = max(0, min(self.readability_score, 100))

    def load_xml(self) -> None:
        """
        加载并解析XML文件，捕获常见异常并记录问题、扣减对应分数
        优化点：
        1. 拆分路径校验逻辑，增强鲁棒性
        2. 抽离分数边界处理
        3. 更清晰的异常分类
        """
        # 1. 路径基础校验
        if not self.file_path.exists():
            error_msg = f"[严重] 文件不存在: {self.file_path}"
            self.issues.append(error_msg)
            self.readability_score -= ScoreDeduction.FILE_NOT_FOUND
            self._clamp_score()
            return

        # 2. 后缀校验
        if self.file_path.suffix.lower() != ".xml":
            self.issues.append(f"[警告] 文件不是XML格式: {self.file_path}")
            self.readability_score -= ScoreDeduction.NON_XML_FILE
            self._clamp_score()

        # 3. 解析XML
        try:
            self.tree = ET.parse(self.file_path)
            self.root = self.tree.getroot()
        except ET.ParseError as e:
            error_msg = f"[严重] XML语法错误: {str(e)}（文件路径：{self.file_path}）"
            self.issues.append(error_msg)
            self.readability_score -= ScoreDeduction.XML_PARSE_ERROR
        except PermissionError as e:
            error_msg = f"[权限] 文件读取权限不足: {str(e)}（文件路径：{self.file_path}）"
            self.issues.append(error_msg)
            self.readability_score -= ScoreDeduction.UNKNOWN_LOAD_ERROR
        except Exception as e:
            error_msg = f"[未知] 文件加载失败: {str(e)}（文件路径：{self.file_path}）"
            self.issues.append(error_msg)
            self.readability_score -= ScoreDeduction.UNKNOWN_LOAD_ERROR

        self._clamp_score()

    def _get_project_jdk_value(self) -> Optional[str]:
        """辅助函数：提取ProjectRootManager中的project-jdk-name值（抽离重复查找逻辑）"""
        if not self.root:
            return None
        
        for component in self.root.findall("component"):
            if component.get("name") == "ProjectRootManager":
                jdk_option = component.find("option[@name='project-jdk-name']")
                if jdk_option:
                    return jdk_option.get("value")
        return None

    def check_config_norm(self) -> List[str]:
        """
        检查配置规范性：
        1. project根节点版本格式（纯数字/数字+小数点）
        2. Python SDK名称（避免特殊字符）
        
        优化点：
        1. 抽离SDK查找逻辑，减少代码重复
        2. 更清晰的条件判断
        3. 补充空值防护
        """
        norm_issues: List[str] = []
        if not self.root:
            return norm_issues

        # 1. 检查project版本格式
        project_version = self.root.get("version")
        if project_version and not VERSION_PATTERN.match(project_version):
            issue = (
                f"[规范] project版本格式不规范: {project_version} "
                f"（建议：纯数字/数字+小数点，如3.8、4）"
            )
            norm_issues.append(issue)
            self.readability_score -= ScoreDeduction.INVALID_VERSION_FORMAT

        # 2. 检查Python SDK命名规范性
        jdk_val = self._get_project_jdk_value()
        if jdk_val and SPECIAL_CHAR_PATTERN.search(jdk_val):
            issue = (
                f"[规范] Python SDK名称含特殊字符: {jdk_val} "
                f"（易导致解析异常，建议仅使用字母/数字/空格/括号）"
            )
            norm_issues.append(issue)
            self.readability_score -= ScoreDeduction.SDK_SPECIAL_CHARS

        self._clamp_score()
        return norm_issues

    def detect_duplicate_config(self) -> List[str]:
        """
        检测重复的component配置项（重复配置会降低可维护性，易引发冲突）
        
        优化点：
        1. 简化重复判断逻辑
        2. 补充空名称component的提示更清晰
        3. 抽离分数边界处理
        """
        duplicate_issues: List[str] = []
        if not self.root:
            return duplicate_issues

        component_names: List[str] = []
        for component in self.root.findall("component"):
            comp_name = component.get("name")
            
            # 空名称校验
            if not comp_name:
                issue = "[规范] 存在无名称的component配置项（建议补充语义化名称，便于维护）"
                duplicate_issues.append(issue)
                self.readability_score -= ScoreDeduction.EMPTY_COMPONENT_NAME
                continue

            # 重复名称校验
            if comp_name in component_names:
                issue = (
                    f"[重复] 存在重复的component配置: {comp_name} "
                    f"（建议合并相同名称的配置项，减少冗余）"
                )
                duplicate_issues.append(issue)
                self.readability_score -= ScoreDeduction.DUPLICATE_COMPONENT
            else:
                component_names.append(comp_name)

        self._clamp_score()
        return duplicate_issues

    def check_version_compatibility(self) -> List[str]:
        """
        检查Python SDK版本兼容性（验证是否为当前主流支持版本）
        
        优化点：
        1. 抽离SDK版本提取逻辑，减少重复代码
        2. 简化版本解析异常处理
        3. 补充更清晰的版本提示
        """
        compat_issues: List[str] = []
        jdk_val = self._get_project_jdk_value()
        
        if not jdk_val or "Python" not in jdk_val:
            return compat_issues

        # 解析Python版本
        version_match = PYTHON_VERSION_PATTERN.search(jdk_val)
        if not version_match:
            issue = f"[兼容] 无法识别Python版本格式: {jdk_val}（建议格式：Python 3.8、Python 3.10）"
            compat_issues.append(issue)
            self.readability_score -= ScoreDeduction.INVALID_PYTHON_VERSION_PARSE
            self._clamp_score()
            return compat_issues

        try:
            python_version = float(version_match.group(1))
            if python_version < MIN_SUPPORTED_PYTHON_VERSION:
                issue = (
                    f"[兼容] Python版本{python_version}过低 "
                    f"（当前最低支持{MIN_SUPPORTED_PYTHON_VERSION}+，升级可降低长期维护成本）"
                )
                compat_issues.append(issue)
                self.readability_score -= ScoreDeduction.PYTHON_VERSION_TOO_LOW
        except ValueError:
            issue = f"[兼容] 无法解析Python版本号: {jdk_val}（建议检查SDK配置的版本格式）"
            compat_issues.append(issue)
            self.readability_score -= ScoreDeduction.INVALID_PYTHON_VERSION_PARSE

        self._clamp_score()
        return compat_issues

    def calculate_maintainability_score(self) -> int:
        """计算整体可维护性得分（确保分数在0-100之间）"""
        self._clamp_score()
        return self.readability_score

    def get_maintainability_grade(self) -> str:
        """
        根据得分判定可维护性等级
        优化点：抽离等级规则为常量，便于扩展（如新增"及格"等级）
        """
        score = self.calculate_maintainability_score()
        for threshold, grade in MAINTAINABILITY_GRADES:
            if score >= threshold:
                return grade
        return "较差"

    def generate_report(self) -> str:
        """
        生成结构化、可视化的可维护性分析报告
        优化点：
        1. 简化问题收集逻辑
        2. 优化报告格式（更易读）
        3. 补充报告生成时间（可选）
        4. 问题列表为空时的提示更友好
        """
        # 收集所有检测问题
        self.issues.extend([
            *self.check_config_norm(),
            *self.detect_duplicate_config(),
            *self.check_version_compatibility()
        ])

        # 构建报告内容
        report_parts = [
            "# XML配置文件可维护性分析报告",
            f"**分析时间**：{Path(__file__).stat().st_mtime if Path(__file__).exists() else 'N/A'}",  # 可选：添加时间
            f"**文件路径**：{self.file_path}",
            f"**整体可维护性得分**：{self.calculate_maintainability_score()}/100",
            f"**可维护性等级**：{self.get_maintainability_grade()}",
            "\n## 一、问题明细",
        ]

        # 添加问题列表
        if self.issues:
            for idx, issue in enumerate(self.issues, 1):
                report_parts.append(f"{idx}. {issue}")
        else:
            report_parts.append("✅ 未检测到任何可维护性问题，配置规范且兼容！")

        # 添加优化建议（更精准）
        report_parts.extend([
            "\n## 二、针对性优化建议",
            "### 配置规范性优化",
            "- 统一project版本格式：仅使用纯数字或数字+小数点（如3.8、4）",
            "- Python SDK名称仅包含字母、数字、空格、括号，避免特殊字符",
            "- 为所有component节点补充语义化名称，便于识别用途",
            "\n### 重复配置优化",
            "- 合并重复的component节点，删除冗余配置项",
            "- 定期检查配置文件，避免重复配置引发的逻辑冲突",
            "\n### 版本兼容性优化",
            f"- 升级Python SDK至{MIN_SUPPORTED_PYTHON_VERSION}+版本，优先选择长期支持（LTS）版本",
            "- 验证SDK版本格式，确保能被IDE和脚本正确解析",
            "\n### 通用可读性优化",
            "- 保持XML文件缩进统一（建议4个空格）",
            "- 为关键配置节点添加注释，说明配置用途",
            "- 定期备份配置文件，避免误修改导致的维护成本上升"
        ])

        # 拼接报告（统一换行格式）
        return "\n".join(report_parts)


# ===================== 执行分析（优化：更健壮的入口逻辑） =====================
if __name__ == "__main__":
    # 使用示例 - 替换为实际的XML文件路径
    XML_FILE_PATH = "OSS/.idea/misc.xml"
    
    # 初始化分析器并生成报告
    try:
        analyzer = XMLMaintainabilityAnalyzer(XML_FILE_PATH)
        report = analyzer.generate_report()
        
        # 打印报告
        print(report)
        
        # 保存报告（优化：使用更有意义的文件名，包含原文件名称）
        report_filename = f"xml_maintainability_report_{Path(XML_FILE_PATH).stem}.md"
        with open(report_filename, "w", encoding="utf-8") as f:
            f.write(report)
        
        print(f"\n📄 报告已保存至: {Path(report_filename).resolve()}")
    except Exception as e:
        print(f"❌ 分析执行失败: {str(e)}")
        # 可选：添加异常日志记录
        # import logging
        # logging.error(f"XML分析失败: {e}", exc_info=True)
