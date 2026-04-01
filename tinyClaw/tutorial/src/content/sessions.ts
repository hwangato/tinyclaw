// ─────────────────────────────────────────────
//  TinyClaw Tutorial — 12 Sessions Data
//  Language: Chinese (zh-CN)
// ─────────────────────────────────────────────

export interface HowItWorksStep {
  step: number;
  title: string;
  description: string;
  code?: string;
}

export interface Change {
  dimension: string;
  before: string;
  after: string;
}

export interface Session {
  id: string;
  title: string;
  subtitle: string;
  layer: LayerKey;
  categoryColor: string;
  loc: number;
  tools: number;
  insight: string;
  problem: string;
  solution: string;
  howItWorks: HowItWorksStep[];
  changes: Change[];
  tryIt: string[];
  sourceFile: string;
}

export type LayerKey = "L1" | "L2" | "L3" | "L4" | "L5" | "L6";

export interface Layer {
  key: LayerKey;
  name: string;
  color: string;
  bgColor: string;
  textColor: string;
  dotColor: string;
  description: string;
}

export const layers: Record<LayerKey, Layer> = {
  L1: {
    key: "L1",
    name: "工具与执行",
    color: "green",
    bgColor: "bg-green-100 dark:bg-green-900/30",
    textColor: "text-green-700 dark:text-green-400",
    dotColor: "bg-green-500",
    description: "Agent 能调用的外部工具与函数，以及执行策略。",
  },
  L2: {
    key: "L2",
    name: "规划与协调",
    color: "blue",
    bgColor: "bg-blue-100 dark:bg-blue-900/30",
    textColor: "text-blue-700 dark:text-blue-400",
    dotColor: "bg-blue-500",
    description: "多步推理、任务拆解、子任务分配与协调机制。",
  },
  L3: {
    key: "L3",
    name: "通信架构",
    color: "purple",
    bgColor: "bg-purple-100 dark:bg-purple-900/30",
    textColor: "text-purple-700 dark:text-purple-400",
    dotColor: "bg-purple-500",
    description: "Agent 之间、Agent 与用户之间的通信协议与消息格式。",
  },
  L4: {
    key: "L4",
    name: "记忆与状态",
    color: "amber",
    bgColor: "bg-amber-100 dark:bg-amber-900/30",
    textColor: "text-amber-700 dark:text-amber-400",
    dotColor: "bg-amber-500",
    description: "短期记忆、长期记忆、状态管理与持久化。",
  },
  L5: {
    key: "L5",
    name: "自动化与安全",
    color: "red",
    bgColor: "bg-red-100 dark:bg-red-900/30",
    textColor: "text-red-700 dark:text-red-400",
    dotColor: "bg-red-500",
    description: "权限控制、沙箱执行、审计日志与安全策略。",
  },
  L6: {
    key: "L6",
    name: "开放生态",
    color: "teal",
    bgColor: "bg-teal-100 dark:bg-teal-900/30",
    textColor: "text-teal-700 dark:text-teal-400",
    dotColor: "bg-teal-500",
    description: "插件系统、第三方集成、标准协议与生态互操作。",
  },
};

// ═══════════════════════════════════════════════
//  All 12 sessions
// ═══════════════════════════════════════════════

export const sessions: Session[] = [
  // ─── S01 Agent Loop ─────────────────────────
  {
    id: "s01",
    title: "Agent Loop",
    subtitle: "最简 Agent：一个循环就够了",
    layer: "L1",
    categoryColor: "green",
    loc: 84,
    tools: 1,
    insight: "模型就是 Agent。代码只是线束。",
    sourceFile: "s01_agent_loop.py",

    problem: `大多数人以为构建 AI Agent 需要复杂的框架和大量代码。但事实恰恰相反——一个最小可运行的 Agent 只需要一个 while 循环加上 OpenAI 的 function calling 接口。

很多初学者直接去用 LangChain、AutoGen 等重型框架，却不理解 Agent 的核心到底是什么。框架隐藏了本质：模型本身就是决策引擎，你的代码只是把模型的决策翻译成行动。

本节课我们从零开始，用 84 行 Python 写出一个能执行 bash 命令的 Agent。你会发现 Agent 的核心模式惊人地简单：调用模型 → 检查是否有工具调用 → 执行工具 → 把结果喂回模型 → 重复。`,

    solution: `
┌─────────────────────────────────────┐
│            Agent Loop               │
│                                     │
│   ┌──────────┐                      │
│   │  User    │                      │
│   │  Input   │                      │
│   └────┬─────┘                      │
│        ▼                            │
│   ┌──────────┐    ┌──────────────┐  │
│   │  OpenAI  │───▶│ tool_calls?  │  │
│   │   API    │    └──────┬───────┘  │
│   └──────────┘           │          │
│        ▲            Yes  │  No      │
│        │                 │   │      │
│   ┌────┴─────┐     ┌────▼───┐      │
│   │ Append   │     │ exec   │  ▼   │
│   │ result   │◀────│ bash() │ Done  │
│   └──────────┘     └────────┘      │
└─────────────────────────────────────┘`,

    howItWorks: [
      {
        step: 1,
        title: "定义工具 schema",
        description:
          "用 OpenAI 的 JSON Schema 格式定义一个 bash 工具，让模型知道它可以执行 shell 命令。",
        code: `tools = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "执行一条 bash 命令并返回 stdout/stderr",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {
                        "type": "string",
                        "description": "要执行的 bash 命令"
                    }
                },
                "required": ["cmd"]
            }
        }
    }
]`,
      },
      {
        step: 2,
        title: "实现工具执行函数",
        description:
          "接收模型返回的命令字符串，用 subprocess 执行，捕获输出和错误。",
        code: `import subprocess

def exec_bash(cmd: str) -> str:
    result = subprocess.run(
        cmd, shell=True,
        capture_output=True, text=True, timeout=30
    )
    return result.stdout + result.stderr`,
      },
      {
        step: 3,
        title: "构建核心 while 循环",
        description:
          "这是 Agent 的心脏。循环不断调用模型，检查是否有 tool_calls，如果有就执行工具并把结果追加到消息列表中。如果没有工具调用，说明模型已经准备好回复用户了。",
        code: `import openai, json

client = openai.OpenAI()
messages = [{"role": "system", "content": "你是一个能执行 bash 命令的助手。"}]

while True:
    user_input = input("You: ")
    messages.append({"role": "user", "content": user_input})

    while True:
        resp = client.chat.completions.create(
            model="gpt-4o", messages=messages, tools=tools
        )
        msg = resp.choices[0].message
        messages.append(msg)

        if not msg.tool_calls:
            print(f"Agent: {msg.content}")
            break

        for tc in msg.tool_calls:
            output = exec_bash(json.loads(tc.function.arguments)["cmd"])
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": output
            })`,
      },
    ],

    changes: [
      { dimension: "基础架构", before: "无（从零开始）", after: "while 循环 + OpenAI function calling" },
      { dimension: "工具", before: "无", after: "1 个 bash 工具" },
      { dimension: "消息管理", before: "无", after: "线性消息列表 messages[]" },
    ],

    tryIt: [
      "python s01_agent_loop.py",
      "# 输入：帮我看看当前目录有哪些文件",
      "# 输入：用 Python 写一个 hello world 并运行它",
      "# 输入：查看当前系统的内存使用情况",
    ],
  },

  // ─── S02 工具系统 ───────────────────────────
  {
    id: "s02",
    title: "工具系统",
    subtitle: "用注册表和装饰器管理工具",
    layer: "L1",
    categoryColor: "green",
    loc: 160,
    tools: 4,
    insight: "让 LLM 自主选择工具，而不是硬编码调用链。",
    sourceFile: "s02_tool_system.py",

    problem: `在 s01 中，我们把 bash 工具直接写死在代码里。如果要添加第二个、第三个工具呢？每次都要修改主循环里的 if-else 分支吗？这种方式完全无法扩展。

更严重的问题是安全性。s01 的 bash 工具可以执行任意命令，包括 rm -rf /。我们需要一种机制来限制工具的能力范围，比如让文件操作只能在指定目录内进行。

本节课引入注册表模式和 @tool 装饰器。工具的定义、注册、发现全部自动化——添加一个新工具只需要写一个函数并加上装饰器，主循环完全不需要改动。同时，我们引入路径沙箱，确保文件操作不会逃出项目目录。`,

    solution: `
┌──────────────────────────────────────────┐
│              Tool Registry               │
│                                          │
│  @tool("bash")    ──┐                    │
│  @tool("read")    ──┤  register()        │
│  @tool("write")   ──┤───────────▶ { }    │
│  @tool("ls")      ──┘           registry │
│                                   │      │
│  Agent Loop                       │      │
│   │                               │      │
│   │  tool_calls: "read"           │      │
│   │───────── lookup(name) ────────┘      │
│   │                                      │
│   │◀──────── result ─────────────        │
│                                          │
│  ┌─── Path Sandbox ──────────────┐       │
│  │  /project/                    │       │
│  │    ├── src/  ✅               │       │
│  │    ├── data/ ✅               │       │
│  │  /etc/passwd ❌ BLOCKED       │       │
│  └───────────────────────────────┘       │
└──────────────────────────────────────────┘`,

    howItWorks: [
      {
        step: 1,
        title: "创建 @tool 装饰器",
        description:
          "装饰器自动提取函数签名，生成 OpenAI 要求的 JSON Schema，并注册到全局字典中。开发者只需要专注于写工具逻辑。",
        code: `TOOL_REGISTRY: dict[str, dict] = {}

def tool(name: str, description: str):
    def decorator(func):
        schema = _build_schema_from_hints(func)
        TOOL_REGISTRY[name] = {
            "function": func,
            "definition": {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": schema
                }
            }
        }
        return func
    return decorator`,
      },
      {
        step: 2,
        title: "用装饰器定义工具",
        description:
          "每个工具就是一个普通的 Python 函数，装饰器负责所有的元数据工作。",
        code: `@tool("read_file", "读取指定路径的文件内容")
def read_file(path: str) -> str:
    safe = sandbox(path)
    return open(safe).read()

@tool("write_file", "将内容写入指定路径")
def write_file(path: str, content: str) -> str:
    safe = sandbox(path)
    with open(safe, "w") as f:
        f.write(content)
    return f"已写入 {safe}"

@tool("list_dir", "列出目录内容")
def list_dir(path: str = ".") -> str:
    safe = sandbox(path)
    return "\\n".join(os.listdir(safe))`,
      },
      {
        step: 3,
        title: "路径沙箱防护",
        description:
          "所有涉及文件路径的工具都通过 sandbox() 函数校验，确保解析后的绝对路径落在允许的目录内。这是最基础的安全措施。",
        code: `SANDBOX_ROOT = os.path.abspath("./project")

def sandbox(path: str) -> str:
    resolved = os.path.abspath(
        os.path.join(SANDBOX_ROOT, path)
    )
    if not resolved.startswith(SANDBOX_ROOT):
        raise PermissionError(
            f"路径 {path} 逃出了沙箱范围"
        )
    return resolved`,
      },
      {
        step: 4,
        title: "主循环自动发现工具",
        description:
          "主循环不再硬编码工具名，而是从注册表动态获取工具列表和执行函数。新增工具时主循环零改动。",
        code: `def get_all_tool_defs() -> list[dict]:
    return [t["definition"] for t in TOOL_REGISTRY.values()]

def dispatch(name: str, arguments: dict) -> str:
    entry = TOOL_REGISTRY.get(name)
    if not entry:
        return f"未知工具: {name}"
    return entry["function"](**arguments)

# 在循环中使用
resp = client.chat.completions.create(
    model="gpt-4o",
    messages=messages,
    tools=get_all_tool_defs()   # 自动获取所有已注册工具
)`,
      },
    ],

    changes: [
      { dimension: "工具管理", before: "硬编码在主循环中", after: "@tool 装饰器 + 注册表自动发现" },
      { dimension: "工具数量", before: "1 个 (bash)", after: "4 个 (bash, read, write, ls)" },
      { dimension: "安全", before: "无任何限制", after: "路径沙箱 sandbox()" },
      { dimension: "扩展性", before: "新增工具需改主循环", after: "新增工具只需写函数 + 装饰器" },
    ],

    tryIt: [
      "python s02_tool_system.py",
      "# 输入：读取 project/config.json 的内容",
      "# 输入：在 project 目录下创建一个新的 Python 文件",
      "# 输入：列出当前项目的目录结构",
    ],
  },

  // ─── S03 Skills 系统 ────────────────────────
  {
    id: "s03",
    title: "Skills 系统",
    subtitle: "按需加载知识，而非全量注入",
    layer: "L2",
    categoryColor: "blue",
    loc: 230,
    tools: 5,
    insight: "摘要在系统提示词，详情按需加载——两层知识架构。",
    sourceFile: "s03_skills.py",

    problem: `随着 Agent 能做的事情越来越多，我们面临一个实际问题：系统提示词放不下所有知识。如果把每个工具的详细用法、每个领域的专业知识全部塞进 system prompt，token 消耗会爆炸，而且模型的注意力会被稀释。

想象一下：你的 Agent 需要会写代码、会部署、会查数据库、会写文档。每个技能的详细说明可能有几千字。全部注入 system prompt？那就是几万 token 的上下文，不仅贵，而且模型表现反而会变差。

解决方案是 Skills 系统——一个两层知识架构。系统提示词里只放每个 Skill 的一句话摘要（"我会做什么"），详细的操作手册（SKILL.md）在模型需要时才加载。就像一本字典：目录（摘要）帮你快速找到词条，翻到对应页（详情）才看完整释义。`,

    solution: `
┌────────────────────────────────────────────────┐
│               Skills Architecture              │
│                                                │
│  System Prompt (always loaded)                 │
│  ┌──────────────────────────────────────────┐  │
│  │ 可用技能:                                │  │
│  │  • deploy — 部署应用到服务器              │  │
│  │  • db_query — 查询 SQL 数据库            │  │
│  │  • code_review — 审查代码质量            │  │
│  │                                          │  │
│  │ 需要详情时调用 load_skill(name)          │  │
│  └──────────────────────────────────────────┘  │
│                     │                          │
│         LLM decides to load "deploy"           │
│                     ▼                          │
│  ┌──────────────────────────────────────────┐  │
│  │  skills/deploy/SKILL.md                  │  │
│  │  ┌────────────────────────────────────┐  │  │
│  │  │ # 部署技能                         │  │  │
│  │  │ ## 步骤                            │  │  │
│  │  │ 1. 检查 Dockerfile                 │  │  │
│  │  │ 2. 构建镜像                        │  │  │
│  │  │ 3. 推送到 registry                 │  │  │
│  │  │ 4. 更新 k8s deployment             │  │  │
│  │  └────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────┘  │
└────────────────────────────────────────────────┘`,

    howItWorks: [
      {
        step: 1,
        title: "定义 Skill 目录结构",
        description:
          "每个 Skill 是一个文件夹，包含 SKILL.md（详细手册）和可选的模板文件。摘要写在 SKILL.md 的第一行。",
        code: `# skills/
# ├── deploy/
# │   └── SKILL.md
# ├── db_query/
# │   └── SKILL.md
# └── code_review/
#     └── SKILL.md

SKILLS_DIR = "./skills"

def scan_skills() -> dict[str, dict]:
    """扫描 skills 目录，返回 {name: {summary, path}}"""
    skills = {}
    for name in os.listdir(SKILLS_DIR):
        md_path = os.path.join(SKILLS_DIR, name, "SKILL.md")
        if os.path.isfile(md_path):
            with open(md_path) as f:
                first_line = f.readline().strip("# \\n")
            skills[name] = {
                "summary": first_line,
                "path": md_path
            }
    return skills`,
      },
      {
        step: 2,
        title: "生成摘要注入 system prompt",
        description:
          "启动时扫描所有 Skill，把名字和一句话摘要拼接成 system prompt 的一部分。模型只看到目录级信息。",
        code: `def build_system_prompt(skills: dict) -> str:
    lines = ["你是一个多技能助手。以下是你掌握的技能：\\n"]
    for name, info in skills.items():
        lines.append(f"  • {name} — {info['summary']}")
    lines.append(
        "\\n需要详细操作步骤时，调用 load_skill(name) 获取完整手册。"
    )
    return "\\n".join(lines)`,
      },
      {
        step: 3,
        title: "注册 load_skill 工具",
        description:
          "这是一个特殊的元工具——它不是执行某个业务操作，而是给模型自己加载知识。模型根据用户请求判断需要哪个技能，主动调用此工具。",
        code: `@tool("load_skill", "加载指定技能的详细操作手册")
def load_skill(name: str) -> str:
    skills = scan_skills()
    if name not in skills:
        return f"未找到技能: {name}。可用: {list(skills.keys())}"
    with open(skills[name]["path"]) as f:
        return f.read()`,
      },
      {
        step: 4,
        title: "工具调用流程",
        description:
          "当用户说「帮我部署应用」，模型看到 system prompt 中有 deploy 摘要，先调用 load_skill('deploy') 获取详细步骤，然后按步骤调用 bash/write 等工具完成实际操作。",
        code: `# 典型的消息流程：
# User: "帮我部署这个项目"
# LLM:  [tool_call: load_skill("deploy")]
# Tool:  "# 部署技能\\n## 步骤\\n1. 检查 Dockerfile..."
# LLM:  [tool_call: bash("docker build -t app .")]
# Tool:  "Successfully built abc123..."
# LLM:  "部署完成！镜像已构建并推送。"`,
      },
    ],

    changes: [
      { dimension: "知识管理", before: "所有信息硬编码在 system prompt", after: "两层架构：摘要常驻 + 详情按需加载" },
      { dimension: "工具", before: "4 个业务工具", after: "5 个（+load_skill 元工具）" },
      { dimension: "Token 效率", before: "知识越多 prompt 越长", after: "system prompt 只有摘要，详情按需加载" },
      { dimension: "可扩展性", before: "添加知识需改代码", after: "添加 Skill 只需新建文件夹和 SKILL.md" },
    ],

    tryIt: [
      "python s03_skills.py",
      "# 输入：帮我部署当前项目到服务器",
      "# 输入：查询数据库中用户表的前 10 条记录",
      "# 输入：审查 src/main.py 的代码质量",
    ],
  },

  // ─── S04 子 Agent ──────────────────────────
  {
    id: "s04",
    title: "子 Agent",
    subtitle: "独立消息空间实现任务隔离",
    layer: "L2",
    categoryColor: "blue",
    loc: 300,
    tools: 6,
    insight: "独立的消息数组就是独立的思维空间。",
    sourceFile: "s04_subagent.py",

    problem: `当 Agent 处理复杂任务时，比如「先分析这段代码，然后写测试，最后生成文档」，所有的中间推理和工具调用结果都堆在同一个消息列表里。随着对话变长，模型的注意力被稀释，前面步骤的上下文会逐渐模糊。

更严重的是任务污染——分析代码时产生的大量中间输出会影响后续写测试的质量。模型看到太多不相关的信息，反而会犯错。这就像让一个人同时在三个白板上推演三件事，互相干扰。

解决方案是子 Agent：每个子任务启动一个独立的 Agent，拥有自己的消息数组和 system prompt。子 Agent 完成后只把最终结果返回给主 Agent。就像经理把任务分给不同的员工，每个人在自己的空间里专注工作，最后只汇报结论。`,

    solution: `
┌─────────────────────────────────────────────────┐
│                 Main Agent                      │
│  messages: [user, assistant, ...]               │
│                                                 │
│  "分析代码并写测试"                               │
│        │                                        │
│        ├──── spawn_subagent("分析代码") ─────┐   │
│        │     ┌─────────────────────────┐     │   │
│        │     │ Sub-Agent A             │     │   │
│        │     │ messages: [独立的历史]    │     │   │
│        │     │ system: "你是代码分析师" │     │   │
│        │     │ → "发现 3 个问题..."     │     │   │
│        │     └─────────────────────────┘     │   │
│        │◀──── result: "发现 3 个问题..." ────┘   │
│        │                                        │
│        ├──── spawn_subagent("写测试") ──────┐   │
│        │     ┌─────────────────────────┐     │   │
│        │     │ Sub-Agent B             │     │   │
│        │     │ messages: [独立的历史]    │     │   │
│        │     │ system: "你是测试工程师" │     │   │
│        │     │ → "已生成 5 个测试用例"  │     │   │
│        │     └─────────────────────────┘     │   │
│        │◀──── result: "已生成 5 个测试用例" ─┘   │
│        ▼                                        │
│  "分析完成并已写好测试"                           │
└─────────────────────────────────────────────────┘`,

    howItWorks: [
      {
        step: 1,
        title: "定义 SubAgent 运行函数",
        description:
          "子 Agent 本质上就是另一个 Agent Loop，但使用独立的 messages 列表。完成后返回最终的文本结果。",
        code: `def run_subagent(
    task: str,
    system_prompt: str,
    tools: list[dict] | None = None
) -> str:
    """运行一个隔离的子 Agent，返回最终结果"""
    sub_messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": task}
    ]
    sub_tools = tools or get_all_tool_defs()

    while True:
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=sub_messages,
            tools=sub_tools
        )
        msg = resp.choices[0].message
        sub_messages.append(msg)

        if not msg.tool_calls:
            return msg.content

        for tc in msg.tool_calls:
            result = dispatch(
                tc.function.name,
                json.loads(tc.function.arguments)
            )
            sub_messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result
            })`,
      },
      {
        step: 2,
        title: "注册 spawn_subagent 工具",
        description:
          "让主 Agent 可以通过工具调用来启动子 Agent。主 Agent 负责分解任务，子 Agent 负责执行。",
        code: `@tool("spawn_subagent", "启动一个子 Agent 执行特定子任务")
def spawn_subagent(task: str, role: str = "通用助手") -> str:
    system = (
        f"你是一个{role}。"
        "请专注完成以下任务，完成后直接给出结果。"
    )
    return run_subagent(task=task, system_prompt=system)`,
      },
      {
        step: 3,
        title: "主 Agent 自动分解任务",
        description:
          "主 Agent 收到复杂请求后，会自动判断是否需要拆分为子任务。每个子 Agent 在独立的消息空间中工作，互不干扰。",
        code: `MAIN_SYSTEM = """你是一个任务协调者。
对于复杂任务，你应该拆分为子任务并使用 spawn_subagent 工具。
每个子任务分配一个合适的角色(role)。
子任务完成后，你负责整合结果并给出最终回答。"""`,
      },
      {
        step: 4,
        title: "结果汇总与隔离",
        description:
          "子 Agent 的返回结果作为工具调用的 output 回到主 Agent 的消息历史中。主 Agent 看到的只是简洁的结论，不会被子任务的中间过程干扰。",
        code: `# 实际消息流：
# Main messages:
#   [user] "分析代码并写测试"
#   [assistant] tool_call: spawn_subagent(task="分析 main.py", role="代码分析师")
#   [tool] "发现 3 个问题: 1)... 2)... 3)..."
#   [assistant] tool_call: spawn_subagent(task="为 main.py 写测试", role="测试工程师")
#   [tool] "已生成 5 个测试用例，覆盖率 85%"
#   [assistant] "分析和测试都完成了。共发现 3 个代码问题..."
#
# Sub-Agent A 的 messages 有 15 条（包含大量中间推理）
# Sub-Agent B 的 messages 有 12 条
# 但主 Agent 只看到 2 条简洁的工具结果`,
      },
    ],

    changes: [
      { dimension: "任务执行", before: "单一 Agent 串行处理所有子任务", after: "主 Agent 分解 + 子 Agent 独立执行" },
      { dimension: "消息隔离", before: "所有任务共享一个 messages 列表", after: "每个子 Agent 拥有独立的 messages" },
      { dimension: "工具", before: "5 个工具", after: "6 个（+spawn_subagent）" },
      { dimension: "上下文污染", before: "子任务的中间过程影响后续推理", after: "子任务结果汇总，中间过程隔离" },
    ],

    tryIt: [
      "python s04_subagent.py",
      "# 输入：分析 src/main.py 的代码质量，然后为它写单元测试",
      "# 输入：用一个子 Agent 查资料，另一个写总结报告",
    ],
  },

  // ─── S05 消息总线 ──────────────────────────
  {
    id: "s05",
    title: "消息总线",
    subtitle: "用 asyncio.Queue 解耦输入与输出",
    layer: "L3",
    categoryColor: "purple",
    loc: 400,
    tools: 6,
    insight: "解耦生产者和消费者，总线是 Agent 走向多渠道的关键。",
    sourceFile: "s05_message_bus.py",

    problem: `到目前为止，我们的 Agent 只有一种交互方式：终端的 input() 和 print()。但真实世界中，Agent 需要对接多个渠道——Telegram、Web API、Slack、甚至语音接口。

如果每个渠道都在 Agent 核心循环里写 if-else，代码会变成意大利面。更糟糕的是，有些渠道是同步的（终端），有些是异步的（Telegram webhook），有些是流式的（WebSocket）。直接耦合意味着每加一个渠道都要大改核心逻辑。

消息总线是解决方案：用 asyncio.Queue 建立双向通道。Agent 核心只从 inbound queue 读消息、向 outbound queue 写消息，完全不关心消息来自哪里、去向何方。渠道适配器负责把各自的协议翻译成统一的消息格式。`,

    solution: `
┌─────────────────────────────────────────────────────┐
│                  Message Bus                        │
│                                                     │
│  ┌─────────┐    InboundQueue     ┌──────────────┐  │
│  │ Terminal │──┐                  │              │  │
│  └─────────┘  │  ┌────────────┐  │              │  │
│               ├─▶│  inbound   │─▶│  Agent Core  │  │
│  ┌─────────┐  │  │  Queue     │  │              │  │
│  │  (API)  │──┘  └────────────┘  │  (不关心     │  │
│  └─────────┘                     │   消息来源)   │  │
│                                  │              │  │
│                  OutboundQueue    │              │  │
│  ┌─────────┐    ┌────────────┐   │              │  │
│  │ Terminal │◀─┐│  outbound  │◀──│              │  │
│  └─────────┘  ││  Queue     │   └──────────────┘  │
│               │└────────────┘                      │
│  ┌─────────┐  │                                    │
│  │  (API)  │◀─┘                                    │
│  └─────────┘                                       │
└─────────────────────────────────────────────────────┘`,

    howItWorks: [
      {
        step: 1,
        title: "定义统一消息类型",
        description:
          "不管消息来自终端还是 Telegram，进入总线后都是同一种数据结构。这是解耦的基础。",
        code: `from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class InboundMessage:
    text: str
    channel: str = "terminal"      # 来源渠道
    user_id: str = "local"
    timestamp: datetime = field(default_factory=datetime.now)

@dataclass
class OutboundMessage:
    text: str
    channel: str = "terminal"      # 目标渠道
    user_id: str = "local"
    timestamp: datetime = field(default_factory=datetime.now)`,
      },
      {
        step: 2,
        title: "创建双向 Queue",
        description:
          "使用 asyncio.Queue 作为总线。Agent 核心和渠道适配器通过 Queue 通信，完全解耦。",
        code: `import asyncio

class MessageBus:
    def __init__(self):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()

    async def send_to_agent(self, msg: InboundMessage):
        await self.inbound.put(msg)

    async def send_to_user(self, msg: OutboundMessage):
        await self.outbound.put(msg)`,
      },
      {
        step: 3,
        title: "Agent 核心改为异步消费者",
        description:
          "Agent 的主循环不再用 input()，而是从 inbound queue 读取消息。处理完后把结果放入 outbound queue。",
        code: `async def agent_loop(bus: MessageBus):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    while True:
        inbound = await bus.inbound.get()
        messages.append({"role": "user", "content": inbound.text})

        while True:
            resp = await aclient.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                tools=get_all_tool_defs()
            )
            msg = resp.choices[0].message
            messages.append(msg)

            if not msg.tool_calls:
                await bus.send_to_user(OutboundMessage(
                    text=msg.content,
                    channel=inbound.channel,
                    user_id=inbound.user_id
                ))
                break

            for tc in msg.tool_calls:
                result = dispatch(
                    tc.function.name,
                    json.loads(tc.function.arguments)
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result
                })`,
      },
      {
        step: 4,
        title: "终端适配器",
        description:
          "终端只是总线的一个渠道适配器。读取用户输入放入 inbound queue，从 outbound queue 读取结果并打印。",
        code: `async def terminal_adapter(bus: MessageBus):
    loop = asyncio.get_event_loop()
    asyncio.create_task(_print_outbound(bus))

    while True:
        text = await loop.run_in_executor(None, input, "You: ")
        if text.strip():
            await bus.send_to_agent(InboundMessage(text=text))

async def _print_outbound(bus: MessageBus):
    while True:
        msg = await bus.outbound.get()
        if msg.channel == "terminal":
            print(f"Agent: {msg.text}")`,
      },
      {
        step: 5,
        title: "启动所有协程",
        description:
          "用 asyncio.gather 同时运行 Agent 核心和所有渠道适配器。未来添加新渠道只需新增一个适配器。",
        code: `async def main():
    bus = MessageBus()
    await asyncio.gather(
        agent_loop(bus),
        terminal_adapter(bus),
        # 未来可以在这里加更多适配器：
        # telegram_adapter(bus),
        # web_api_adapter(bus),
    )

asyncio.run(main())`,
      },
    ],

    changes: [
      { dimension: "I/O 模型", before: "同步 input() / print()", after: "异步 asyncio.Queue 双向总线" },
      { dimension: "架构", before: "Agent 直接读写终端", after: "Agent 通过总线间接通信，渠道可插拔" },
      { dimension: "并发", before: "单线程阻塞", after: "asyncio 协程并发" },
      { dimension: "扩展性", before: "只支持终端", after: "总线架构支持任意数量的渠道适配器" },
    ],

    tryIt: [
      "python s05_message_bus.py",
      "# 输入：帮我看看当前目录有什么文件",
      "# 观察消息在总线中的流转过程",
    ],
  },

  // ─── S06 接入 Telegram ─────────────────────
  {
    id: "s06",
    title: "接入 Telegram",
    subtitle: "一套接口，多平台对接",
    layer: "L3",
    categoryColor: "purple",
    loc: 520,
    tools: 6,
    insight: "一套接口对接多平台——抽象是复用的基础。",
    sourceFile: "s06_telegram.py",

    problem: `上节课我们建好了消息总线，但只有终端一个适配器。现在要接入 Telegram——这是一个真实的外部平台，有自己的 API、Webhook、消息格式和用户系统。

如果我们直接在代码里硬编码 Telegram 的 API 调用，那以后接 Slack、Discord、微信每个都要写一遍类似的逻辑。而且 Telegram 的消息格式和我们的 InboundMessage 完全不同，需要翻译。

解决方案是定义 Channel 抽象协议（Python 的 Protocol 或 ABC）。每个平台只需要实现 receive() 和 send() 两个方法。Telegram 适配器负责把 Telegram 的 Update 对象翻译成 InboundMessage，把 OutboundMessage 翻译成 Telegram 的 sendMessage 调用。核心 Agent 代码完全不变。`,

    solution: `
┌──────────────────────────────────────────────────────┐
│            Channel Abstraction                       │
│                                                      │
│  ┌──────────────────────────────────────────────┐    │
│  │         Protocol: Channel                    │    │
│  │                                              │    │
│  │   async def receive() -> InboundMessage      │    │
│  │   async def send(msg: OutboundMessage)       │    │
│  └──────────────────┬───────────────────────────┘    │
│                     │                                │
│          ┌──────────┼──────────┐                     │
│          ▼          ▼          ▼                     │
│  ┌────────────┐ ┌────────┐ ┌────────┐               │
│  │ Terminal   │ │Telegram│ │ Slack  │  (future)     │
│  │ Channel    │ │Channel │ │Channel │               │
│  └─────┬──────┘ └───┬────┘ └───┬────┘               │
│        │            │          │                     │
│        └──────┬─────┘──────────┘                     │
│               ▼                                      │
│        ┌────────────┐                                │
│        │ MessageBus │                                │
│        └──────┬─────┘                                │
│               ▼                                      │
│        ┌────────────┐                                │
│        │ Agent Core │                                │
│        └────────────┘                                │
└──────────────────────────────────────────────────────┘`,

    howItWorks: [
      {
        step: 1,
        title: "定义 Channel 协议",
        description:
          "用 Python 的 typing.Protocol 定义渠道接口，所有平台适配器必须实现这两个方法。",
        code: `from typing import Protocol

class Channel(Protocol):
    name: str

    async def start(self, bus: MessageBus) -> None:
        """启动渠道，开始监听消息"""
        ...

    async def send(self, msg: OutboundMessage) -> None:
        """将 Agent 的回复发送到对应平台"""
        ...`,
      },
      {
        step: 2,
        title: "实现 Telegram Channel",
        description:
          "Telegram 适配器使用 python-telegram-bot 库，监听消息并翻译为 InboundMessage 格式。",
        code: `from telegram import Update, Bot
from telegram.ext import Application, MessageHandler, filters

class TelegramChannel:
    name = "telegram"

    def __init__(self, token: str):
        self.bot = Bot(token)
        self.app = Application.builder().token(token).build()
        self.bus: MessageBus | None = None

    async def start(self, bus: MessageBus) -> None:
        self.bus = bus
        self.app.add_handler(
            MessageHandler(filters.TEXT, self._on_message)
        )
        asyncio.create_task(self._dispatch_outbound())
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()

    async def _on_message(self, update: Update, ctx):
        await self.bus.send_to_agent(InboundMessage(
            text=update.message.text,
            channel="telegram",
            user_id=str(update.effective_user.id),
        ))`,
      },
      {
        step: 3,
        title: "实现 outbound 分发",
        description:
          "从 outbound queue 读取消息，判断 channel 字段，调用对应平台的发送方法。",
        code: `    async def _dispatch_outbound(self):
        while True:
            msg = await self.bus.outbound.get()
            if msg.channel == "telegram":
                await self.send(msg)

    async def send(self, msg: OutboundMessage) -> None:
        chat_id = msg.metadata.get("chat_id")
        if chat_id:
            await self.bot.send_message(
                chat_id=chat_id, text=msg.text
            )`,
      },
      {
        step: 4,
        title: "统一注册渠道",
        description:
          "启动时把所有渠道注册到总线上，Agent 核心不需要知道有哪些渠道。",
        code: `async def main():
    bus = MessageBus()

    channels: list[Channel] = [
        TerminalChannel(),
        TelegramChannel(token=os.getenv("TELEGRAM_BOT_TOKEN")),
    ]

    for ch in channels:
        await ch.start(bus)

    await agent_loop(bus)

asyncio.run(main())`,
      },
    ],

    changes: [
      { dimension: "渠道架构", before: "只有终端适配器，无抽象", after: "Channel Protocol + 多渠道注册" },
      { dimension: "外部平台", before: "无", after: "Telegram Bot 接入" },
      { dimension: "消息路由", before: "所有输出到终端", after: "按 channel 字段路由到对应平台" },
      { dimension: "代码组织", before: "单文件", after: "渠道适配器可独立为模块" },
    ],

    tryIt: [
      "TELEGRAM_BOT_TOKEN=xxx python s06_telegram.py",
      "# 在 Telegram 上给 Bot 发送一条消息",
      "# 同时在终端和 Telegram 与 Agent 对话",
    ],
  },

  // ─── S07 持久化记忆 ────────────────────────
  {
    id: "s07",
    title: "持久化记忆",
    subtitle: "SQLite + MEMORY.md 让 Agent 记住一切",
    layer: "L4",
    categoryColor: "amber",
    loc: 650,
    tools: 8,
    insight: "没有记忆的 Agent 只是一个函数；有记忆才是一个伙伴。",
    sourceFile: "s07_memory.py",

    problem: `目前我们的 Agent 每次重启都会失忆。消息历史存在内存里，程序一关就全没了。用户昨天告诉 Agent 的偏好、聊过的项目、做过的决定——全部归零。

这不仅仅是用户体验的问题，更是能力问题。一个有记忆的 Agent 可以说「上次你提到要用 FastAPI，我来延续那个方案」；一个没记忆的 Agent 每次都要重新了解用户需求。

本节课引入两层持久化机制：SQLite 存储完整的会话历史（结构化数据），MEMORY.md 存储 Agent 的长期认知笔记（非结构化知识）。Agent 可以主动往 MEMORY.md 里写入重要信息，比如用户偏好、项目约定、关键决策。每次启动时加载上次的会话并读取 MEMORY.md 注入上下文。`,

    solution: `
┌───────────────────────────────────────────────────┐
│              Memory Architecture                  │
│                                                   │
│  ┌──────────────┐    ┌───────────────────────┐    │
│  │  MEMORY.md   │    │   SQLite Database     │    │
│  │              │    │                       │    │
│  │  ## 用户偏好 │    │  sessions             │    │
│  │  - 喜欢简洁  │    │  ┌─────┬─────┬─────┐  │    │
│  │  - 用 Python │    │  │ id  │start│ end │  │    │
│  │              │    │  └─────┴─────┴─────┘  │    │
│  │  ## 项目约定 │    │                       │    │
│  │  - 用 ruff   │    │  messages             │    │
│  │  - 测试覆盖  │    │  ┌─────┬──────┬────┐  │    │
│  │    > 80%     │    │  │sess │role  │text│  │    │
│  └──────┬───────┘    │  └─────┴──────┴────┘  │    │
│         │            └──────────┬────────────┘    │
│         │                       │                 │
│         ▼                       ▼                 │
│  ┌──────────────────────────────────────────┐     │
│  │              Agent Startup               │     │
│  │                                          │     │
│  │  1. 从 SQLite 加载最近会话消息            │     │
│  │  2. 从 MEMORY.md 读取长期记忆             │     │
│  │  3. 注入 system prompt                   │     │
│  └──────────────────────────────────────────┘     │
└───────────────────────────────────────────────────┘`,

    howItWorks: [
      {
        step: 1,
        title: "设计 SQLite 数据模型",
        description:
          "两张表：sessions 记录每次会话的开始/结束时间，messages 记录每条消息的角色、内容和时间戳。",
        code: `import sqlite3

def init_db(path: str = "memory.db") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT DEFAULT (datetime('now')),
            ended_at TEXT
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER REFERENCES sessions(id),
            role TEXT NOT NULL,
            content TEXT,
            tool_calls TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    return conn`,
      },
      {
        step: 2,
        title: "会话持久化与恢复",
        description:
          "每次启动时创建新 session 或恢复最近 session。每条消息实时写入数据库，崩溃也不会丢数据。",
        code: `class SessionStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.session_id = self._create_session()

    def _create_session(self) -> int:
        cur = self.conn.execute(
            "INSERT INTO sessions DEFAULT VALUES"
        )
        self.conn.commit()
        return cur.lastrowid

    def save_message(self, role: str, content: str,
                     tool_calls: str = None):
        self.conn.execute(
            "INSERT INTO messages "
            "(session_id, role, content, tool_calls) "
            "VALUES (?, ?, ?, ?)",
            (self.session_id, role, content, tool_calls)
        )
        self.conn.commit()

    def load_recent(self, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "SELECT role, content FROM messages "
            "WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (self.session_id, limit)
        ).fetchall()
        return [
            {"role": r, "content": c}
            for r, c in reversed(rows)
        ]`,
      },
      {
        step: 3,
        title: "MEMORY.md 长期记忆",
        description:
          "Agent 可以通过 save_memory 工具把重要信息写入 MEMORY.md。每次启动时读取并注入 system prompt。这是 Agent 的「笔记本」。",
        code: `MEMORY_PATH = "./MEMORY.md"

@tool("save_memory", "将重要信息保存到长期记忆")
def save_memory(content: str, section: str = "通用") -> str:
    existing = ""
    if os.path.exists(MEMORY_PATH):
        with open(MEMORY_PATH) as f:
            existing = f.read()

    header = f"## {section}"
    if header in existing:
        existing = existing.replace(
            header, f"{header}\\n- {content}"
        )
    else:
        existing += f"\\n\\n{header}\\n- {content}"

    with open(MEMORY_PATH, "w") as f:
        f.write(existing)
    return f"已保存到 [{section}] 章节"

@tool("read_memory", "读取长期记忆")
def read_memory() -> str:
    if os.path.exists(MEMORY_PATH):
        with open(MEMORY_PATH) as f:
            return f.read()
    return "（暂无长期记忆）"`,
      },
      {
        step: 4,
        title: "启动时注入记忆",
        description:
          "把 MEMORY.md 的内容作为 system prompt 的一部分，让 Agent 从一开始就拥有历史认知。",
        code: `def build_system_prompt_with_memory() -> str:
    memory = ""
    if os.path.exists(MEMORY_PATH):
        with open(MEMORY_PATH) as f:
            memory = f.read()

    return f"""你是一个智能助手，拥有持久化记忆。

## 你的长期记忆
{memory if memory else "（暂无记忆，可用 save_memory 保存重要信息）"}

遇到重要信息（用户偏好、项目约定、关键决策）时，
请主动使用 save_memory 工具保存。"""`,
      },
    ],

    changes: [
      { dimension: "记忆", before: "内存中的 messages 列表，重启即丢失", after: "SQLite 持久化 + MEMORY.md 长期记忆" },
      { dimension: "工具", before: "6 个工具", after: "8 个（+save_memory, +read_memory）" },
      { dimension: "会话管理", before: "无会话概念", after: "Session 记录，支持恢复历史对话" },
      { dimension: "用户体验", before: "每次重启都是全新对话", after: "Agent 记住偏好、约定和历史上下文" },
    ],

    tryIt: [
      "python s07_memory.py",
      "# 输入：记住我喜欢用 ruff 做代码格式化",
      "# 重启后输入：上次我们聊了什么？",
    ],
  },

  // ─── S08 上下文压缩 ────────────────────────
  {
    id: "s08",
    title: "上下文压缩",
    subtitle: "三层策略让长对话永不断裂",
    layer: "L4",
    categoryColor: "amber",
    loc: 750,
    tools: 9,
    insight: "Token 有限，摘要无限——压缩是长对话的生命线。",
    sourceFile: "s08_compression.py",

    problem: `有了持久化记忆后，新问题出现了：对话越长，token 越多，成本越高，速度越慢。GPT-4o 有 128K 的上下文窗口，但一个活跃用户一天的对话量就可能超过这个限制。

更关键的是，即使上下文窗口足够大，模型对超长上下文中间部分的注意力也会衰减（"lost in the middle" 问题）。把 200 条消息全部喂给模型，不如把前 180 条压缩成摘要，只保留最近 20 条完整消息。

本节课实现三层压缩策略：(1) 微压缩——自动截断过长的工具输出；(2) 自动压缩——当消息数超过阈值时自动摘要；(3) 手动压缩——用户或 Agent 主动触发 compact 命令。压缩后的摘要会替换原始消息，大幅减少 token 同时保留关键上下文。`,

    solution: `
┌───────────────────────────────────────────────────────┐
│           Three-Layer Compression                     │
│                                                       │
│  Layer 1: 微压缩 (每次工具调用后)                       │
│  ┌────────────────────────────────────────────┐       │
│  │ tool output > 2000 chars?                  │       │
│  │   → 截断 + "[已截断，共 N 字符]"             │       │
│  └────────────────────────────────────────────┘       │
│                                                       │
│  Layer 2: 自动压缩 (消息数 > 阈值)                     │
│  ┌────────────────────────────────────────────┐       │
│  │ messages > 40?                             │       │
│  │   → 保留最近 10 条                          │       │
│  │   → 前 30 条 → LLM 摘要                    │       │
│  │   → [system, summary, ...recent_10]        │       │
│  └────────────────────────────────────────────┘       │
│                                                       │
│  Layer 3: 手动压缩 (/compact 命令)                     │
│  ┌────────────────────────────────────────────┐       │
│  │ 用户触发 → 全量摘要当前对话                   │       │
│  │   → 只保留 system + summary                 │       │
│  └────────────────────────────────────────────┘       │
│                                                       │
│  messages: [system] [summary] [...recent messages]    │
└───────────────────────────────────────────────────────┘`,

    howItWorks: [
      {
        step: 1,
        title: "微压缩：截断过长输出",
        description:
          "工具输出超过指定长度时自动截断。这是最简单也最频繁触发的压缩层。比如 ls -la 输出 1000 行文件列表，只保留首尾部分。",
        code: `MAX_TOOL_OUTPUT = 2000

def truncate_output(output: str) -> str:
    if len(output) <= MAX_TOOL_OUTPUT:
        return output
    half = MAX_TOOL_OUTPUT // 2
    return (
        output[:half]
        + f"\\n\\n... [已截断，原始 {len(output)} 字符] ...\\n\\n"
        + output[-half:]
    )`,
      },
      {
        step: 2,
        title: "自动压缩：消息数超阈值",
        description:
          "每次 Agent 循环结束后检查消息数量。超过阈值时，把旧消息发给 LLM 做摘要，用摘要替换原始消息。",
        code: `AUTO_COMPACT_THRESHOLD = 40
KEEP_RECENT = 10

async def auto_compact(messages: list[dict]) -> list[dict]:
    if len(messages) <= AUTO_COMPACT_THRESHOLD:
        return messages

    system = messages[0]
    old = messages[1:-KEEP_RECENT]
    recent = messages[-KEEP_RECENT:]

    summary = await summarize(old)

    return [
        system,
        {"role": "user",
         "content": f"[之前对话的摘要]\\n{summary}"},
        {"role": "assistant",
         "content": "好的，我已了解之前的对话内容。"},
        *recent
    ]`,
      },
      {
        step: 3,
        title: "LLM 驱动的摘要生成",
        description:
          "摘要本身也由 LLM 生成，能够理解语义并提取关键信息，比简单截断好得多。",
        code: `async def summarize(messages: list[dict]) -> str:
    resp = await aclient.chat.completions.create(
        model="gpt-4o-mini",  # 用便宜模型做摘要
        messages=[
            {"role": "system", "content": (
                "请将以下对话摘要为简洁的要点。"
                "保留：关键决策、用户偏好、重要结果。"
                "删除：中间推理、重复内容、工具原始输出。"
            )},
            {"role": "user",
             "content": format_messages(messages)}
        ]
    )
    return resp.choices[0].message.content`,
      },
      {
        step: 4,
        title: "手动压缩工具",
        description:
          "注册一个 compact 工具，让用户或 Agent 随时可以主动触发全量压缩。",
        code: `@tool("compact", "压缩当前对话历史，生成摘要以节省 token")
async def compact() -> str:
    global messages
    before = count_tokens(messages)
    messages = await auto_compact_force(messages)
    after = count_tokens(messages)
    saved = before - after
    return (
        f"压缩完成。token: {before} → {after}，"
        f"节省 {saved} ({saved*100//before}%)"
    )`,
      },
    ],

    changes: [
      { dimension: "Token 管理", before: "消息无限增长，直到超出上下文窗口", after: "三层压缩策略自动控制 token 用量" },
      { dimension: "工具", before: "8 个工具", after: "9 个（+compact）" },
      { dimension: "长对话", before: "对话过长时模型性能退化", after: "自动摘要保留关键上下文" },
      { dimension: "成本", before: "token 成本随对话线性增长", after: "压缩后成本大幅降低" },
      { dimension: "工具输出", before: "原样返回，可能很长", after: "超长输出自动截断" },
    ],

    tryIt: [
      "python s08_compression.py",
      "# 持续对话 50 轮后观察自动压缩触发",
      "# 输入：帮我压缩一下当前对话",
    ],
  },

  // ─── S09 定时任务 ──────────────────────────
  {
    id: "s09",
    title: "定时任务",
    subtitle: "让 Agent 主动巡逻世界",
    layer: "L5",
    categoryColor: "red",
    loc: 880,
    tools: 12,
    insight: "Agent 不只是被动回答问题，还能主动巡逻世界。",
    sourceFile: "s09_scheduler.py",

    problem: `到目前为止，我们的 Agent 是被动的——用户发消息，Agent 才响应。但很多有价值的场景需要 Agent 主动行动：每天早上 8 点汇总昨天的 Git 提交，每小时检查服务器健康状态，每周生成项目进度报告。

这些定时任务不能靠用户手动触发。我们需要一个内建的调度器，让 Agent 能够注册和管理定时任务。而且这些任务执行的是 bash 命令和脚本，必须有安全门控——不能让定时任务不经审查就执行危险操作。

本节课实现三种调度模式：Cron（类 crontab 表达式）、Interval（固定间隔）、Once（一次性延迟执行）。同时引入脚本门控机制，确保定时执行的命令都经过审查。`,

    solution: `
┌────────────────────────────────────────────────────────┐
│               Scheduler System                         │
│                                                        │
│  ┌──────────────────────────────────────────────┐      │
│  │           Schedule Registry                  │      │
│  │                                              │      │
│  │  ┌────────┬────────────┬──────────────┐      │      │
│  │  │ Type   │ Expression │ Script       │      │      │
│  │  ├────────┼────────────┼──────────────┤      │      │
│  │  │ cron   │ 0 8 * * *  │ daily_report │      │      │
│  │  │interval│ 3600s      │ health_check │      │      │
│  │  │ once   │ +30m       │ deploy_check │      │      │
│  │  └────────┴────────────┴──────────────┘      │      │
│  └──────────────────┬───────────────────────────┘      │
│                     │                                  │
│                     ▼                                  │
│  ┌──────────────────────────────────────────────┐      │
│  │            Scheduler Loop                    │      │
│  │                                              │      │
│  │  while True:                                 │      │
│  │    for job in registry:                      │      │
│  │      if job.is_due():                        │      │
│  │        ┌─── Gate Check ───┐                  │      │
│  │        │ script approved? │                  │      │
│  │        │  ✅ → execute    │                  │      │
│  │        │  ❌ → skip + log │                  │      │
│  │        └──────────────────┘                  │      │
│  │    await asyncio.sleep(1)                    │      │
│  └──────────────────────────────────────────────┘      │
│                                                        │
│  Results → MessageBus → User                           │
└────────────────────────────────────────────────────────┘`,

    howItWorks: [
      {
        step: 1,
        title: "定义任务数据模型",
        description:
          "每个定时任务包含 ID、类型（cron/interval/once）、调度表达式、要执行的脚本路径和是否经过审批。",
        code: `from dataclasses import dataclass
from enum import Enum

class ScheduleType(Enum):
    CRON = "cron"
    INTERVAL = "interval"
    ONCE = "once"

@dataclass
class ScheduledJob:
    id: str
    type: ScheduleType
    expression: str       # cron: "0 8 * * *", interval: "3600"
    script: str           # 脚本路径或命令
    description: str
    approved: bool = False  # 门控：需要审批才能执行
    last_run: float = 0
    enabled: bool = True`,
      },
      {
        step: 2,
        title: "实现调度器循环",
        description:
          "调度器作为一个独立的 asyncio task 运行，每秒检查所有注册的任务是否到了执行时间。",
        code: `import asyncio
from croniter import croniter
from datetime import datetime

class Scheduler:
    def __init__(self, bus: MessageBus):
        self.jobs: dict[str, ScheduledJob] = {}
        self.bus = bus

    async def run(self):
        while True:
            now = datetime.now()
            for job in self.jobs.values():
                if not job.enabled:
                    continue
                if self._is_due(job, now):
                    await self._execute(job)
            await asyncio.sleep(1)

    def _is_due(self, job, now) -> bool:
        if job.type == ScheduleType.CRON:
            it = croniter(job.expression,
                         datetime.fromtimestamp(job.last_run))
            return it.get_next(datetime) <= now
        elif job.type == ScheduleType.INTERVAL:
            return (now.timestamp() - job.last_run
                    >= float(job.expression))
        return False`,
      },
      {
        step: 3,
        title: "脚本门控机制",
        description:
          "定时执行的命令必须经过审批。未审批的任务会被跳过并发出警告。用户可以通过 approve_job 工具审批。",
        code: `    async def _execute(self, job: ScheduledJob):
        if not job.approved:
            await self.bus.send_to_user(OutboundMessage(
                text=f"[警告] 任务 [{job.id}] 未审批，已跳过。\\n"
                     f"执行内容: {job.script}\\n"
                     f"使用 approve_job('{job.id}') 审批。",
                channel="terminal"
            ))
            return

        job.last_run = datetime.now().timestamp()
        result = exec_bash(job.script)
        await self.bus.send_to_user(OutboundMessage(
            text=f"[定时任务 {job.id}] 执行完毕:\\n{result}",
            channel="terminal"
        ))`,
      },
      {
        step: 4,
        title: "注册调度工具",
        description:
          "Agent 可以通过工具调用来创建、列出、删除和审批定时任务。",
        code: `@tool("create_job", "创建一个定时任务")
def create_job(id: str, type: str, expression: str,
               script: str, description: str) -> str:
    job = ScheduledJob(
        id=id, type=ScheduleType(type),
        expression=expression, script=script,
        description=description
    )
    scheduler.jobs[id] = job
    return (f"任务 [{id}] 已创建（待审批）。"
            f"类型: {type}, 表达式: {expression}")

@tool("approve_job", "审批定时任务，允许其执行")
def approve_job(id: str) -> str:
    if id not in scheduler.jobs:
        return f"未找到任务: {id}"
    scheduler.jobs[id].approved = True
    return f"任务 [{id}] 已审批。"

@tool("list_jobs", "列出所有定时任务")
def list_jobs() -> str:
    if not scheduler.jobs:
        return "暂无定时任务"
    lines = []
    for j in scheduler.jobs.values():
        status = "已审批" if j.approved else "待审批"
        lines.append(
            f"  [{j.id}] {j.type.value} "
            f"{j.expression} — {j.description} ({status})"
        )
    return "\\n".join(lines)`,
      },
    ],

    changes: [
      { dimension: "执行模式", before: "纯被动响应，用户不说话 Agent 就静默", after: "支持定时主动执行任务" },
      { dimension: "调度", before: "无", after: "Cron / Interval / Once 三种调度模式" },
      { dimension: "安全", before: "路径沙箱", after: "路径沙箱 + 脚本门控审批机制" },
      { dimension: "工具", before: "9 个工具", after: "12 个（+create_job, +approve_job, +list_jobs）" },
    ],

    tryIt: [
      "python s09_scheduler.py",
      "# 输入：每小时检查一下服务器的磁盘使用情况",
      "# 输入：列出当前所有定时任务的状态",
    ],
  },

  // ─── S10 容器隔离 ──────────────────────────
  {
    id: "s10",
    title: "容器隔离",
    subtitle: "Docker 沙箱 + 策略引擎",
    layer: "L5",
    categoryColor: "red",
    loc: 1050,
    tools: 14,
    insight: "OS 级隔离 > 应用级权限——沙箱是信任的边界。",
    sourceFile: "s10_container.py",

    problem: `之前的安全措施（路径沙箱 + 脚本门控）都是应用层面的。一个精心构造的命令可以绕过 Python 代码里的路径检查，比如通过符号链接、环境变量注入或者命令拼接。本质上，只要 Agent 能直接访问宿主机的进程和文件系统，就存在安全风险。

在生产环境中，Agent 执行的命令应该在隔离的容器里运行。即使 LLM 被提示注入攻击（prompt injection），生成了恶意命令，破坏的也只是一个可以随时丢弃的容器，而不是你的服务器。

本节课引入 Docker 沙箱和策略引擎。每次 bash 执行都在一个受限的 Docker 容器中运行，策略引擎在执行前检查命令是否违反安全策略（比如禁止网络访问、禁止挂载敏感目录）。采用「拒绝优先」原则——默认拒绝，只有明确允许的操作才放行。`,

    solution: `
┌──────────────────────────────────────────────────────────┐
│              Container Isolation                         │
│                                                          │
│  Agent Tool Call: bash("rm -rf /important")              │
│         │                                                │
│         ▼                                                │
│  ┌──────────────────────────────────────┐                │
│  │        Policy Engine                 │                │
│  │                                      │                │
│  │  ┌─────────────────────────────┐     │                │
│  │  │ Rule 1: block rm -rf /      │ ❌  │                │
│  │  │ Rule 2: block curl | bash   │     │                │
│  │  │ Rule 3: allow read-only     │ ✅  │                │
│  │  │ Rule 4: allow /project/*    │ ✅  │                │
│  │  └─────────────────────────────┘     │                │
│  │                                      │                │
│  │  Default: DENY                       │                │
│  └──────────┬───────────────────────────┘                │
│             │ ✅ Approved                                │
│             ▼                                            │
│  ┌──────────────────────────────────────┐                │
│  │        Docker Container              │                │
│  │  ┌──────────────────────────────┐    │                │
│  │  │ • 无网络访问                 │    │                │
│  │  │ • CPU/Memory 限制           │    │                │
│  │  │ • 30s 超时自动销毁          │    │                │
│  │  │ • /project 只挂载项目目录    │    │                │
│  │  └──────────────────────────────┘    │                │
│  │        ↓ stdout/stderr               │                │
│  └──────────┬───────────────────────────┘                │
│             ▼                                            │
│       Result → Agent                                     │
└──────────────────────────────────────────────────────────┘`,

    howItWorks: [
      {
        step: 1,
        title: "策略引擎定义",
        description:
          "策略引擎维护一组规则，每条规则可以 ALLOW 或 DENY 某类命令。按顺序匹配，第一条命中的规则生效。默认策略是 DENY。",
        code: `from dataclasses import dataclass
from enum import Enum
import re

class Action(Enum):
    ALLOW = "allow"
    DENY = "deny"

@dataclass
class PolicyRule:
    pattern: str       # 正则匹配命令
    action: Action
    reason: str

class PolicyEngine:
    def __init__(self):
        self.rules: list[PolicyRule] = [
            PolicyRule(r"rm\\s+-rf\\s+/[^p]",
                      Action.DENY, "禁止删除系统目录"),
            PolicyRule(r"curl.*\\|.*bash",
                      Action.DENY, "禁止远程执行脚本"),
            PolicyRule(r"chmod\\s+777",
                      Action.DENY, "禁止开放所有权限"),
            PolicyRule(r"(ls|cat|head|tail|wc|grep)",
                      Action.ALLOW, "只读命令"),
            PolicyRule(r"python",
                      Action.ALLOW, "允许运行 Python"),
        ]
        self.default = Action.DENY

    def check(self, cmd: str) -> tuple[Action, str]:
        for rule in self.rules:
            if re.search(rule.pattern, cmd):
                return rule.action, rule.reason
        return self.default, "默认策略：拒绝未知命令"`,
      },
      {
        step: 2,
        title: "Docker 沙箱执行",
        description:
          "命令通过策略检查后，在 Docker 容器中执行。容器设置了严格的资源限制和隔离策略。",
        code: `import docker

class DockerSandbox:
    def __init__(self, project_dir: str):
        self.client = docker.from_env()
        self.project_dir = os.path.abspath(project_dir)

    def execute(self, cmd: str, timeout: int = 30) -> str:
        try:
            output = self.client.containers.run(
                image="python:3.12-slim",
                command=["bash", "-c", cmd],
                volumes={
                    self.project_dir: {
                        "bind": "/project", "mode": "rw"
                    }
                },
                working_dir="/project",
                network_disabled=True,   # 禁止网络
                mem_limit="256m",        # 内存限制
                cpu_period=100000,
                cpu_quota=50000,         # 50% CPU
                remove=True,             # 执行完自动销毁
                timeout=timeout
            )
            return output.decode("utf-8")
        except docker.errors.ContainerError as e:
            return f"执行失败: {e.stderr.decode()}"
        except Exception as e:
            return f"沙箱错误: {str(e)}"`,
      },
      {
        step: 3,
        title: "安全 bash 工具",
        description:
          "替换原来的 bash 工具。先过策略引擎，再在 Docker 中执行。两道关卡缺一不可。",
        code: `policy = PolicyEngine()
sandbox = DockerSandbox("./project")

@tool("bash", "在安全沙箱中执行 bash 命令")
def safe_bash(cmd: str) -> str:
    # 第一关：策略引擎
    action, reason = policy.check(cmd)
    if action == Action.DENY:
        return f"命令被策略引擎拒绝: {reason}\\n命令: {cmd}"

    # 第二关：Docker 沙箱
    return sandbox.execute(cmd)`,
      },
      {
        step: 4,
        title: "策略管理工具",
        description:
          "提供工具让 Agent 或管理员查看和测试安全策略。",
        code: `@tool("list_policies", "查看当前安全策略规则")
def list_policies() -> str:
    lines = ["当前安全策略（按优先级排列）：\\n"]
    for i, rule in enumerate(policy.rules, 1):
        icon = "ALLOW" if rule.action == Action.ALLOW else "DENY"
        lines.append(f"  {i}. [{icon}] {rule.pattern} — {rule.reason}")
    default = "拒绝" if policy.default == Action.DENY else "允许"
    lines.append(f"\\n默认策略: {default}")
    return "\\n".join(lines)

@tool("test_policy", "测试一条命令是否会被策略引擎放行")
def test_policy(cmd: str) -> str:
    action, reason = policy.check(cmd)
    result = "放行" if action == Action.ALLOW else "拒绝"
    return f"命令: {cmd}\\n结果: {result} — {reason}"`,
      },
    ],

    changes: [
      { dimension: "执行环境", before: "宿主机直接执行命令", after: "Docker 容器隔离执行" },
      { dimension: "安全模型", before: "路径沙箱（应用层）", after: "策略引擎 + Docker（OS 层）+ 拒绝优先" },
      { dimension: "工具", before: "12 个工具", after: "14 个（+list_policies, +test_policy）" },
      { dimension: "资源限制", before: "仅超时限制", after: "CPU / 内存 / 网络 / 文件系统全面限制" },
      { dimension: "安全默认值", before: "默认允许", after: "默认拒绝，白名单放行" },
    ],

    tryIt: [
      "python s10_container.py",
      "# 输入：在沙箱里运行 python -c 'print(1+1)'",
      "# 输入：测试 rm -rf / 会不会被阻止",
    ],
  },

  // ─── S11 MCP 协议 ─────────────────────────
  {
    id: "s11",
    title: "MCP 协议",
    subtitle: "标准协议让 Agent 连接一切",
    layer: "L6",
    categoryColor: "teal",
    loc: 1250,
    tools: 15,
    insight: "标准协议让 Agent 连接一切——MCP 是 Agent 的 USB。",
    sourceFile: "s11_mcp.py",

    problem: `我们的 Agent 现在有了丰富的内建工具，但能力仍然是封闭的。如果想让 Agent 访问 GitHub、Jira、数据库或任何第三方服务，就必须在 Agent 代码里写适配器。每集成一个服务就要改一次代码，维护成本随服务数量线性增长。

更大的问题是生态。如果每个 Agent 框架都定义自己的工具协议，那工具提供方需要为每个框架写一遍适配，社区无法形成合力。这就像 USB 标准出现之前，每个设备都有自己的接口。

MCP（Model Context Protocol）是 Anthropic 提出的 Agent 工具协议标准。它基于 JSON-RPC 2.0，通过 Stdio 传输，定义了工具发现（tools/list）、工具调用（tools/call）等标准化接口。任何实现了 MCP 协议的外部进程都可以为 Agent 提供工具，无需修改 Agent 核心代码。`,

    solution: `
┌──────────────────────────────────────────────────────────┐
│                   MCP Architecture                       │
│                                                          │
│  Agent Core                                              │
│  ┌────────────────────────────────────────────────────┐  │
│  │  Tool Registry                                     │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────────────┐   │  │
│  │  │ built-in │ │ built-in │ │  mcp::github/    │   │  │
│  │  │ bash     │ │ read     │ │  create_issue    │   │  │
│  │  └──────────┘ └──────────┘ └────────┬─────────┘   │  │
│  └──────────────────────────────────────┼─────────────┘  │
│                                         │                │
│                    JSON-RPC 2.0 / Stdio │                │
│                                         ▼                │
│  ┌──────────────────────────────────────────────────┐    │
│  │          MCP Server (external process)            │    │
│  │                                                   │    │
│  │  ← tools/list                                     │    │
│  │    → [{name: "create_issue", ...}, ...]           │    │
│  │                                                   │    │
│  │  ← tools/call {name, arguments}                   │    │
│  │    → {content: [{type: "text", text: "Done!"}]}   │    │
│  │                                                   │    │
│  │  Process: node github-mcp-server.js               │    │
│  └──────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘`,

    howItWorks: [
      {
        step: 1,
        title: "JSON-RPC 2.0 传输层",
        description:
          "MCP 使用 JSON-RPC 2.0 作为消息格式，通过 Stdio（stdin/stdout）与外部 MCP Server 进程通信。每条消息以换行符分隔。",
        code: `import json, asyncio
from asyncio.subprocess import Process

class McpClient:
    def __init__(self, name: str, command: list[str]):
        self.name = name
        self.command = command
        self.process: Process | None = None
        self._id = 0

    async def start(self):
        self.process = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    async def _send(self, method: str, params: dict = None) -> dict:
        self._id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._id,
            "method": method,
            "params": params or {}
        }
        line = json.dumps(request) + "\\n"
        self.process.stdin.write(line.encode())
        await self.process.stdin.drain()

        resp_line = await self.process.stdout.readline()
        return json.loads(resp_line)`,
      },
      {
        step: 2,
        title: "工具发现 (tools/list)",
        description:
          "启动 MCP Server 后，首先调用 tools/list 获取它提供的所有工具的 schema。这些工具会被注册到 Agent 的工具注册表中。",
        code: `    async def discover_tools(self) -> list[dict]:
        resp = await self._send("tools/list")
        tools = resp.get("result", {}).get("tools", [])
        return tools

    # 返回的工具格式：
    # [
    #   {
    #     "name": "create_issue",
    #     "description": "在 GitHub 创建一个 issue",
    #     "inputSchema": {
    #       "type": "object",
    #       "properties": {
    #         "repo": {"type": "string"},
    #         "title": {"type": "string"},
    #         "body": {"type": "string"}
    #       },
    #       "required": ["repo", "title"]
    #     }
    #   }
    # ]`,
      },
      {
        step: 3,
        title: "工具调用 (tools/call)",
        description:
          "当 Agent 需要调用 MCP 工具时，发送 tools/call 请求到对应的 MCP Server 进程。",
        code: `    async def call_tool(self, name: str, arguments: dict) -> str:
        resp = await self._send("tools/call", {
            "name": name,
            "arguments": arguments
        })
        result = resp.get("result", {})
        contents = result.get("content", [])
        return "\\n".join(
            c["text"] for c in contents
            if c.get("type") == "text"
        )`,
      },
      {
        step: 4,
        title: "命名空间集成",
        description:
          "MCP 工具使用 mcp::serverName/toolName 的命名空间格式注册，避免和内建工具冲突。Agent 的 dispatch 函数识别前缀并路由到对应的 MCP Client。",
        code: `class McpManager:
    def __init__(self):
        self.clients: dict[str, McpClient] = {}

    async def register(self, name: str, command: list[str]):
        client = McpClient(name, command)
        await client.start()
        tools = await client.discover_tools()
        self.clients[name] = client

        for t in tools:
            ns = f"mcp::{name}/{t['name']}"
            TOOL_REGISTRY[ns] = {
                "function": lambda a, c=client, n=t["name"]:
                    c.call_tool(n, a),
                "definition": {
                    "type": "function",
                    "function": {
                        "name": ns,
                        "description": t["description"],
                        "parameters": t.get("inputSchema", {})
                    }
                }
            }

# await mcp.register("github", ["node", "github-mcp.js"])
# Agent 自动获得 mcp::github/create_issue 等工具`,
      },
      {
        step: 5,
        title: "生命周期管理",
        description:
          "MCP Server 是外部进程，需要在 Agent 退出时正确关闭。",
        code: `    async def shutdown(self):
        for name, client in self.clients.items():
            if client.process:
                client.process.stdin.close()
                await client.process.wait()
                print(f"MCP Server [{name}] 已关闭")

async def main():
    mcp = McpManager()
    await mcp.register("github", ["node", "github-mcp.js"])
    try:
        await agent_loop(bus)
    finally:
        await mcp.shutdown()`,
      },
    ],

    changes: [
      { dimension: "工具扩展", before: "只有内建工具，添加新工具需改代码", after: "MCP 协议动态发现和调用外部工具" },
      { dimension: "协议", before: "自定义工具调用逻辑", after: "JSON-RPC 2.0 标准协议" },
      { dimension: "传输", before: "进程内函数调用", after: "Stdio 进程间通信" },
      { dimension: "工具", before: "14 个内建工具", after: "15 个（+MCP 动态工具，数量无上限）" },
      { dimension: "生态", before: "封闭的工具体系", after: "兼容 MCP 生态的所有工具服务" },
    ],

    tryIt: [
      "python s11_mcp.py",
      "# 启动 MCP 工具服务器后连接",
      "# 输入：列出当前所有可用的 MCP 工具",
    ],
  },

  // ─── S12 插件系统 ─────────────────────────
  {
    id: "s12",
    title: "插件系统",
    subtitle: "语言无关的扩展机制",
    layer: "L6",
    categoryColor: "teal",
    loc: 1500,
    tools: 16,
    insight: "语言无关的扩展机制——让社区定义 Agent 的能力边界。",
    sourceFile: "s12_plugins.py",

    problem: `MCP 解决了工具集成的问题，但它只覆盖了「工具调用」这一种扩展场景。一个成熟的插件系统需要支持更多扩展点：Agent 启动时执行初始化、消息处理前后执行拦截器、定时任务触发时执行自定义逻辑。

而且 MCP 目前主要面向工具提供方。我们需要一个面向社区开发者的插件框架，让他们能用任何编程语言（Python、Node.js、Go、Rust）来扩展 Agent 的行为。插件不应该需要直接修改 Agent 源码。

本节课在 MCP 的基础上构建完整的插件系统：复用 JSON-RPC 2.0 协议与 Stdio 传输，新增钩子系统（lifecycle hooks）和进程管理。每个插件是一个独立进程，通过标准接口注册工具和钩子，Agent 在关键生命周期节点自动调用已注册的钩子。`,

    solution: `
┌──────────────────────────────────────────────────────────────┐
│                    Plugin System                             │
│                                                              │
│  Agent Core                                                  │
│  ┌────────────────────────────────────────────────────────┐  │
│  │                                                        │  │
│  │  Lifecycle Hooks                                       │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │  │
│  │  │on_start  │ │on_msg_in │ │on_msg_out│ │on_stop   │  │  │
│  │  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘  │  │
│  │       │            │            │            │         │  │
│  │  Plugin Manager                                        │  │
│  │  ┌──────────────────────────────────────────────────┐  │  │
│  │  │  plugins: {name: PluginProcess}                  │  │  │
│  │  │                                                  │  │  │
│  │  │  register_tools()   → TOOL_REGISTRY              │  │  │
│  │  │  register_hooks()   → HOOK_REGISTRY              │  │  │
│  │  │  fire_hook(event)   → notify all subscribers     │  │  │
│  │  └──────────┬──────────────────────┬────────────────┘  │  │
│  └─────────────┼──────────────────────┼───────────────────┘  │
│                │ JSON-RPC / Stdio     │ JSON-RPC / Stdio     │
│      ┌─────────▼──────────┐ ┌────────▼───────────┐          │
│      │ Plugin: analytics  │ │ Plugin: translator  │          │
│      │ (Python)           │ │ (Node.js)           │          │
│      │                    │ │                     │          │
│      │ tools:             │ │ tools:              │          │
│      │  - track_event     │ │  - translate        │          │
│      │ hooks:             │ │ hooks:              │          │
│      │  - on_msg_out      │ │  - on_msg_in        │          │
│      └────────────────────┘ └─────────────────────┘          │
└──────────────────────────────────────────────────────────────┘`,

    howItWorks: [
      {
        step: 1,
        title: "插件清单格式",
        description:
          "每个插件需要一个 plugin.json 清单文件，声明名称、启动命令、提供的工具和订阅的钩子。",
        code: `# plugins/analytics/plugin.json
{
    "name": "analytics",
    "version": "1.0.0",
    "description": "追踪 Agent 的使用数据",
    "command": ["python", "main.py"],
    "tools": ["track_event", "get_stats"],
    "hooks": {
        "on_start": true,
        "on_message_out": true,
        "on_stop": true
    }
}`,
      },
      {
        step: 2,
        title: "插件管理器",
        description:
          "管理器负责扫描插件目录、启动插件进程、注册工具和钩子、以及在 Agent 退出时关闭所有插件。",
        code: `class PluginManager:
    def __init__(self, plugins_dir: str = "./plugins"):
        self.plugins_dir = plugins_dir
        self.plugins: dict[str, McpClient] = {}
        self.hook_registry: dict[str, list[str]] = {
            "on_start": [],
            "on_message_in": [],
            "on_message_out": [],
            "on_stop": [],
        }

    async def load_all(self):
        for name in os.listdir(self.plugins_dir):
            manifest_path = os.path.join(
                self.plugins_dir, name, "plugin.json"
            )
            if not os.path.isfile(manifest_path):
                continue
            with open(manifest_path) as f:
                manifest = json.load(f)
            await self._start_plugin(name, manifest)

    async def _start_plugin(self, name: str, manifest: dict):
        cmd = manifest["command"]
        client = McpClient(name, cmd)
        await client.start()

        # 注册工具（复用 MCP 协议）
        tools = await client.discover_tools()
        for t in tools:
            ns = f"plugin::{name}/{t['name']}"
            TOOL_REGISTRY[ns] = {
                "function": lambda a, c=client, n=t["name"]:
                    c.call_tool(n, a),
                "definition": _to_openai_def(ns, t)
            }

        # 注册钩子
        for hook, enabled in manifest.get("hooks", {}).items():
            if enabled:
                self.hook_registry[hook].append(name)

        self.plugins[name] = client
        print(f"插件 [{name}] 已加载：{len(tools)} 个工具")`,
      },
      {
        step: 3,
        title: "钩子触发机制",
        description:
          "在 Agent 的关键生命周期节点，调用所有订阅了该钩子的插件。钩子调用是异步并发的，不阻塞主流程。",
        code: `    async def fire_hook(self, event: str, data: dict = None):
        subscribers = self.hook_registry.get(event, [])
        tasks = []
        for plugin_name in subscribers:
            client = self.plugins.get(plugin_name)
            if client:
                tasks.append(
                    client._send("hooks/notify", {
                        "event": event,
                        "data": data or {}
                    })
                )
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

# 在 Agent 核心循环中触发钩子：
async def agent_loop(bus, plugins):
    await plugins.fire_hook("on_start")

    while True:
        inbound = await bus.inbound.get()
        await plugins.fire_hook("on_message_in", {
            "text": inbound.text,
            "channel": inbound.channel
        })

        # ... Agent 处理逻辑 ...

        await plugins.fire_hook("on_message_out", {
            "text": response_text
        })`,
      },
      {
        step: 4,
        title: "编写一个示例插件",
        description:
          "一个 Python 写的 analytics 插件，追踪每条消息并提供统计工具。插件本身是一个简单的 JSON-RPC Server。",
        code: `# plugins/analytics/main.py
import sys, json

stats = {"messages_in": 0, "messages_out": 0}

def handle(request):
    method = request["method"]

    if method == "tools/list":
        return {"tools": [{
            "name": "get_stats",
            "description": "获取 Agent 使用统计",
            "inputSchema": {"type": "object", "properties": {}}
        }]}
    elif method == "tools/call":
        return {"content": [
            {"type": "text", "text": json.dumps(stats)}
        ]}
    elif method == "hooks/notify":
        event = request["params"]["event"]
        if event == "on_message_in":
            stats["messages_in"] += 1
        elif event == "on_message_out":
            stats["messages_out"] += 1
        return {"ok": True}

# JSON-RPC Stdio 主循环
for line in sys.stdin:
    req = json.loads(line.strip())
    result = handle(req)
    resp = {"jsonrpc": "2.0", "id": req["id"], "result": result}
    print(json.dumps(resp), flush=True)`,
      },
      {
        step: 5,
        title: "进程管理与优雅退出",
        description:
          "Agent 关闭时先通知所有插件执行清理（触发 on_stop 钩子），然后终止进程。",
        code: `    async def shutdown(self):
        # 先触发 on_stop 钩子，让插件保存状态
        await self.fire_hook("on_stop")

        # 关闭所有插件进程
        for name, client in self.plugins.items():
            if client.process and client.process.returncode is None:
                client.process.terminate()
                try:
                    await asyncio.wait_for(
                        client.process.wait(), timeout=5
                    )
                except asyncio.TimeoutError:
                    client.process.kill()
                print(f"插件 [{name}] 已关闭")

async def main():
    plugins = PluginManager()
    await plugins.load_all()
    try:
        await agent_loop(bus, plugins)
    finally:
        await plugins.shutdown()`,
      },
    ],

    changes: [
      { dimension: "扩展机制", before: "MCP 只支持工具扩展", after: "插件系统支持工具 + 钩子 + 生命周期" },
      { dimension: "语言支持", before: "只有 Python 内建工具", after: "任何语言都可以写插件（JSON-RPC Stdio）" },
      { dimension: "钩子系统", before: "无", after: "on_start / on_message_in / on_message_out / on_stop" },
      { dimension: "工具", before: "15 个工具", after: "16 个（+插件贡献的工具，数量无上限）" },
      { dimension: "进程管理", before: "MCP Server 手动管理", after: "PluginManager 统一管理插件进程生命周期" },
    ],

    tryIt: [
      "python s12_plugins.py",
      "# 输入：列出当前加载了哪些插件",
      "# 输入：查看 analytics 插件的使用统计",
    ],
  },
];

// ═══════════════════════════════════════════════
//  Helper functions
// ═══════════════════════════════════════════════

export function getSession(id: string): Session | undefined {
  return sessions.find((s) => s.id === id);
}

export function getSessionsByLayer(layer: LayerKey): Session[] {
  return sessions.filter((s) => s.layer === layer);
}

export function getAdjacentSessions(
  id: string
): { prev: Session | undefined; next: Session | undefined } {
  const idx = sessions.findIndex((s) => s.id === id);
  return {
    prev: idx > 0 ? sessions[idx - 1] : undefined,
    next: idx < sessions.length - 1 ? sessions[idx + 1] : undefined,
  };
}
