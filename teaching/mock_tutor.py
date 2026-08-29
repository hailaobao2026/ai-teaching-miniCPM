from __future__ import annotations

from .models import LessonResponse, RecognizeResponse, Step
from .subjects import normalize_subject, subject_name, SUBJECT_FOCUS
from .text_utils import normalize_problem_text


SAMPLE_PROBLEM = "解方程：2x + 5 = 17。"

EXAMPLES = [
    {"id": "math-equation", "subject": "math", "title": "一元一次方程", "problem": SAMPLE_PROBLEM, "tag": "代数", "level": "初一"},
    {"id": "math-function", "subject": "math", "title": "一次函数斜率", "problem": "直线 y = 2x - 3 与 x 轴交于点 A，求点 A 的坐标。", "tag": "函数", "level": "初二"},
    {"id": "math-geometry", "subject": "math", "title": "三角形面积", "problem": "在三角形 ABC 中，底边 BC=8，高 AD=5，求三角形 ABC 的面积。", "tag": "几何", "level": "初一"},
    {"id": "chinese-reading", "subject": "chinese", "title": "阅读理解", "problem": "结合文章内容，概括主人公发生变化的原因。", "tag": "阅读", "level": "小学六年级"},
    {"id": "english-grammar", "subject": "english", "title": "英语语法", "problem": "Choose the correct tense and explain why: She has lived here for five years.", "tag": "语法", "level": "初二"},
    {"id": "physics-force", "subject": "physics", "title": "力与运动", "problem": "物体受到水平拉力和摩擦力，如何判断它的运动状态？", "tag": "力学", "level": "初二"},
    {"id": "chemistry-reaction", "subject": "chemistry", "title": "化学方程式", "problem": "写出水分解的化学方程式，并说明反应类型。", "tag": "化学反应", "level": "初三"},
    {"id": "politics-material", "subject": "politics", "title": "材料分析", "problem": "结合材料，说明诚信对个人成长和社会发展的意义。", "tag": "道德与法治", "level": "初二"},
    {"id": "history-cause", "subject": "history", "title": "历史因果", "problem": "根据材料，分析工业革命发生的条件及其影响。", "tag": "世界史", "level": "初三"},
    {"id": "geography-map", "subject": "geography", "title": "地图判读", "problem": "读等高线地形图，判断山谷、山脊和适合修路的位置。", "tag": "地图", "level": "初一"},
    {"id": "biology-cell", "subject": "biology", "title": "细胞结构", "problem": "说明细胞膜的结构特点与控制物质进出的功能。", "tag": "生命结构", "level": "初一"},
]


def recognize(problem_text: str | None = None, subject: str = "math") -> RecognizeResponse:
    text = (problem_text or "").strip() or SAMPLE_PROBLEM
    return RecognizeResponse(subject=normalize_subject(subject), problem=text, confidence=0.94 if problem_text else 0.9, source="mock", needs_confirmation=True)


def _normalise(text: str) -> str:
    return normalize_problem_text(text)


def _response(
    hint: str,
    full: str,
    steps: list[Step],
    answer: str,
    next_question: str,
    confidence: float,
    stage: str,
) -> LessonResponse:
    steps = [
        Step(
            title=step.title,
            body="完整解析后再查看这一步。" if stage == "hint" and step.state == "locked" else step.body,
            state=step.state,
        )
        for step in steps
    ]
    return LessonResponse(
        stage=stage,
        reply=hint if stage == "hint" else full,
        steps=steps,
        final_answer=None if stage == "hint" else answer,
        next_question=next_question,
        confidence=confidence,
        source="mock",
    )


def _equation(problem: str, stage: str) -> LessonResponse | None:
    expression = problem.split("：", 1)[-1].split(":", 1)[-1]
    key = _normalise(expression).replace("x", "x")
    solutions = {
        "2x+5=17": ("x = 6", "两边同时减去 5，再两边同时除以 2。", "2x+5=17 → 2x=12 → x=6"),
        "3x-4=11": ("x = 5", "两边同时加上 4，再两边同时除以 3。", "3x-4=11 → 3x=15 → x=5"),
        "5x+2=27": ("x = 5", "两边同时减去 2，再两边同时除以 5。", "5x+2=27 → 5x=25 → x=5"),
        "7x-9=19": ("x = 4", "两边同时加上 9，再两边同时除以 7。", "7x-9=19 → 7x=28 → x=4"),
        "4x-2=20": ("x = 7", "先两边同时除以 4，再两边同时加上 2。", "4(x-2)=20 → x-2=5 → x=7"),
        "2x+3=18": ("x = 6", "先两边同时除以 2，再两边同时减去 3。", "2(x+3)=18 → x+3=9 → x=6"),
        "x/3+2=6": ("x = 12", "两边同时减去 2，再两边同时乘以 3。", "x/3+2=6 → x/3=4 → x=12"),
        "6x=42": ("x = 7", "两边同时除以 x 的系数 6。", "6x=42 → x=7"),
    }
    data = solutions.get(key)
    if not data:
        return None
    answer, operation, full = data
    steps = [
        Step(title="识别结构", body="这是一个一元一次方程，目标是把未知数单独留在等号一侧。", state="done"),
        Step(title="保持等式平衡", body=operation, state="active" if stage == "hint" else "done"),
        Step(title="得到结果", body=f"所以 {answer}。", state="locked" if stage == "hint" else "active"),
    ]
    return _response("先想想：等式两边怎样用逆运算逐步把含 x 的一项单独留下来？", full, steps, answer, "你想先尝试第一步逆运算吗？", 0.97, stage)


def _factor(problem: str, stage: str) -> LessonResponse | None:
    key = _normalise(problem)
    data = {
        "分解因式x²-9": ("(x - 3)(x + 3)", "这是平方差公式 a²-b²=(a-b)(a+b)。", "x²-9=(x-3)(x+3)"),
        "分解因式x²+6x+9": ("(x + 3)²", "这是完全平方公式 a²+2ab+b²=(a+b)²。", "x²+6x+9=(x+3)²"),
    }.get(key)
    if not data:
        return None
    answer, rule, full = data
    steps = [Step(title="观察结构", body="先判断多项式符合哪一个乘法公式。", state="done"), Step(title="套用公式", body=rule, state="active"), Step(title="写出因式", body=f"所以结果是 {answer}。", state="locked" if stage == "hint" else "active")]
    return _response("先看各项的次数和系数：它更像平方差，还是完全平方？", full, steps, answer, "你能说出对应的公式吗？", 0.96, stage)


FUNCTIONS = {
    "直线y=2x-3与x轴交于点a求点a的坐标": ("(3/2, 0)", "x 轴上的点满足 y=0。", "令 0=2x-3，解得 x=3/2，所以 A=(3/2,0)。"),
    "函数y=3x+1中x=2时y的值是多少": ("7", "把 x=2 代入函数表达式。", "y=3×2+1=7。"),
    "直线y=-x+4的斜率是多少": ("-1", "一次函数 y=kx+b 中，x 的系数 k 就是斜率。", "比较 y=-x+4 与 y=kx+b，得到 k=-1。"),
    "点2,5是否在直线y=2x+1上": ("是", "把点的横坐标代入直线，检查纵坐标是否相等。", "2×2+1=5，与点的纵坐标相同，所以在直线上。"),
    "一次函数y=kx+2经过点1,5求k": ("3", "把点 (1,5) 代入 y=kx+2。", "5=k×1+2，解得 k=3。"),
    "直线y=4x-8与y轴交于何处": ("(0, -8)", "y 轴上的点满足 x=0。", "令 x=0，得到 y=-8，所以交点为 (0,-8)。"),
    "函数y=-2x+6中y=0时x是多少": ("3", "令函数值 y=0，再解关于 x 的方程。", "0=-2x+6，解得 x=3。"),
    "两点0,22,6确定的直线斜率是多少": ("2", "斜率等于纵坐标差除以横坐标差。", "k=(6-2)/(2-0)=2。"),
}


def _function(problem: str, stage: str) -> LessonResponse | None:
    key = _normalise(problem).replace("（", "(").replace("）", ")")
    data = FUNCTIONS.get(key)
    if not data:
        return None
    answer, rule, full = data
    steps = [Step(title="确定条件", body=rule, state="done"), Step(title="代入计算", body="将已知坐标或函数值代入表达式。", state="active"), Step(title="得到结论", body=f"所以答案是 {answer}。", state="locked" if stage == "hint" else "active")]
    return _response("先找出这道题需要令哪个坐标为 0，或把哪个已知值代入函数。", full, steps, answer, "你能先指出要代入的条件吗？", 0.95, stage)


GEOMETRY = {
    "三角形底边bc=8高ad=5求三角形abc的面积": ("20", "三角形面积=底×高÷2。", "S=8×5÷2=20。"),
    "矩形长6宽4求面积": ("24", "矩形面积=长×宽。", "S=6×4=24。"),
    "直角三角形两直角边为3和4求斜边": ("5", "直角三角形使用勾股定理 a²+b²=c²。", "c=√(3²+4²)=5。"),
    "圆的半径为3取π=3.14求面积": ("28.26", "圆面积=πr²。", "S=3.14×3²=28.26。"),
    "平行四边形底边10高6求面积": ("60", "平行四边形面积=底×高。", "S=10×6=60。"),
    "等腰三角形两腰均为5底边为6求周长": ("16", "三角形周长是三边长度之和。", "C=5+5+6=16。"),
    "正方形边长7求对角线": ("7√2", "正方形对角线可由勾股定理求出。", "d=√(7²+7²)=7√2。"),
    "梯形上底4下底8高5求面积": ("30", "梯形面积=(上底+下底)×高÷2。", "S=(4+8)×5÷2=30。"),
}


def _geometry(problem: str, stage: str) -> LessonResponse | None:
    data = GEOMETRY.get(_normalise(problem))
    if not data:
        return None
    answer, rule, full = data
    steps = [Step(title="选择公式", body=rule, state="done"), Step(title="代入数据", body="把题目给出的长度代入公式。", state="active"), Step(title="计算结果", body=f"所以结果是 {answer}。", state="locked" if stage == "hint" else "active")]
    return _response("先判断图形类型，再回忆它对应的面积、周长或勾股公式。", full, steps, answer, "你能先说出这个图形的关键公式吗？", 0.96, stage)


COORDINATES = {
    "点a-2,3关于x轴的对称点是什么": ("(-2, -3)", "关于 x 轴对称时，横坐标不变，纵坐标变号。", "A(-2,3) 关于 x 轴的对称点为 (-2,-3)。"),
    "点b4,-1到原点的距离是多少": ("√17", "点到原点的距离使用 √(x²+y²)。", "d=√(4²+(-1)²)=√17。"),
    "两点1,24,6的中点坐标是什么": ("(5/2, 4)", "中点横、纵坐标分别取两端点坐标的平均值。", "M=((1+4)/2,(2+6)/2)=(5/2,4)。"),
    "直线y=x+2在x=-3时的y值是多少": ("-1", "把 x=-3 代入 y=x+2。", "y=-3+2=-1。"),
}


def _coordinates(problem: str, stage: str) -> LessonResponse | None:
    data = COORDINATES.get(_normalise(problem))
    if not data:
        return None
    answer, rule, full = data
    steps = [Step(title="确定关系", body=rule, state="done"), Step(title="代入坐标", body="将已知坐标代入对应公式。", state="active"), Step(title="得到结果", body=f"所以答案是 {answer}。", state="locked" if stage == "hint" else "active")]
    return _response("先回忆坐标变换或距离/中点公式，再把已知坐标代入。", full, steps, answer, "你能先写出这类题的公式吗？", 0.95, stage)


def _generic_subject_lesson(problem: str, message: str, stage: str, subject: str) -> LessonResponse:
    name = subject_name(subject)
    focus = SUBJECT_FOCUS[normalize_subject(subject)]
    locked = "完整解析后再查看这一步。" if stage == "hint" else "先用题干中的证据完成这一环。"
    steps = [
        Step(title="提取信息", body=f"先圈出题干中的关键词、已知条件和问题目标，关注{focus}。", state="done"),
        Step(title="建立依据", body=f"回忆{ name }的相关概念或规律，把题干信息与知识点对应起来。", state="active"),
        Step(title="组织答案", body=locked if stage == "hint" else "用完整句子或规范符号写出结论，并检查是否回应了题目要求。", state="locked" if stage == "hint" else "active"),
    ]
    full = f"这是一道{ name }题。先从题干提取关键信息，再依据相关知识点组织答案：{problem}"
    return _response(
        f"先别急着写结论：这道{ name }题可以先找出题干证据，再判断它对应哪个知识点。你已经确认了哪些条件？",
        full,
        steps,
        "请根据题干证据写出结论。",
        "你能先指出题目中的关键词或已知条件吗？",
        0.78,
        stage,
    )


def lesson(problem: str, message: str, stage: str, subject: str = "math") -> LessonResponse:
    problem = problem.strip()
    subject = normalize_subject(subject)
    if subject != "math":
        response = _generic_subject_lesson(problem, message, stage, subject)
        response.subject = subject
        response.source = "mock"
        return response
    for solver in (_equation, _factor, _function, _geometry, _coordinates):
        result = solver(problem, stage)
        if result:
            return result
    return LessonResponse(
        stage=stage,
        reply="我先把题目拆成几个小问题。请告诉我：你已经知道哪些条件，卡在哪一步？",
        steps=[Step(title="确认题意", body="请检查题面中的已知量、未知量和求解目标。", state="active"), Step(title="选择方法", body="根据题型选择方程、函数或几何关系。", state="locked"), Step(title="逐步验证", body="每完成一步，都检查等式或单位是否合理。", state="locked")],
        final_answer=None,
        next_question="你希望从识别已知条件开始，还是先看一个提示？",
        confidence=0.68,
        source="mock",
    )
