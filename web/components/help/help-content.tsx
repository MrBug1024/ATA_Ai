"use client";

import {
  Rocket,
  BriefcaseBusiness,
  MessageSquare,
  Quote,
  Network,
  ClipboardCheck,
  Lightbulb,
} from "lucide-react";

/** 帮助中心的纯内容数据;对话框骨架见 help-dialog.tsx。 */
export interface Section {
  id: string;
  title: string;
  icon: typeof Rocket;
  content: React.ReactNode;
}

function Step({ n, children }: { n: number; children: React.ReactNode }) {
  return (
    <li className="flex gap-3">
      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/15 text-[11px] font-semibold text-primary">
        {n}
      </span>
      <span className="flex-1 leading-relaxed">{children}</span>
    </li>
  );
}

function Tip({ children }: { children: React.ReactNode }) {
  return (
    <div className="mt-3 rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs leading-relaxed text-amber-700 dark:text-amber-400">
      💡 {children}
    </div>
  );
}

function H({ children }: { children: React.ReactNode }) {
  return <h3 className="mb-2 mt-4 text-sm font-semibold first:mt-0">{children}</h3>;
}

function P({ children }: { children: React.ReactNode }) {
  return <p className="mb-2 text-sm leading-relaxed text-muted-foreground">{children}</p>;
}

export const HELP_SECTIONS: Section[] = [
  {
    id: "start",
    title: "快速开始",
    icon: Rocket,
    content: (
      <>
        <P>
          AI 会计师是面向年度财务报表审计的智能工作平台。你可以上传账套、报表、函证与支持性资料，
          通过 AI 对话执行审计分析、生成工作底稿和审计报告，并从每一条结论追溯到原始证据。
        </P>
        <H>左侧导航</H>
        <ul className="space-y-2 text-sm">
          <Step n={1}>
            <b>新建对话</b> —— 直接向 AI 提问，或选定一个年审项目执行审计程序。
          </Step>
          <Step n={2}>
            <b>年审项目</b> —— 查看项目年度、资料完整性与任务状态，上传资料并进入项目工作台。
          </Step>
          <Step n={3}>
            <b>最近对话</b> —— 历史会话随时可回看，标「年审」的对话带项目上下文。
          </Step>
        </ul>
        <Tip>
          底部「设置」里可切换浅色 / 深色主题，并开启「显示节点跟踪」查看 AI 每一步的执行细节。
        </Tip>
      </>
    ),
  },
  {
    id: "cases",
    title: "年审项目管理",
    icon: BriefcaseBusiness,
    content: (
      <>
        <P>「年审项目」是所有业务的起点。每一行展示被审计单位、审计年度、任务和资料处理状态。</P>
        <H>项目数据</H>
        <P>项目、成员、结构化账套、会话、证据、关系图谱和报告引用统一存储在年度审计 PostgreSQL。</P>
        <H>常用操作</H>
        <ul className="space-y-2 text-sm">
          <Step n={1}>
            <b>创建年审项目</b> —— 填写项目名称、被审计单位和审计年度。
          </Step>
          <Step n={2}>
            <b>添加材料</b> —— 上传科目余额表、序时账、银行流水、应收明细或其他审计资料。
          </Step>
          <Step n={3}>
            <b>项目工作台 →</b> —— 查看资料处理、结论演进、待补资料、审计调整和关系图谱。
          </Step>
        </ul>
        <Tip>资料上传后会执行原件存储、结构化识别、OCR、证据切片和图谱抽取，可在项目工作台追踪进度。</Tip>
      </>
    ),
  },
  {
    id: "chat",
    title: "AI 对话与审计",
    icon: MessageSquare,
    content: (
      <>
        <P>对话是所有审计业务的主入口，可做资料检查、科目分析、审计程序、证据核验、底稿与报告生成。</P>
        <H>绑定年审项目</H>
        <P>
          在输入框输入 <code className="rounded bg-muted px-1 py-0.5 text-xs">/case</code>{" "}
          会弹出项目选择器，选定后对话即带上审计年度、被审计单位、账套和证据上下文。
        </P>
        <H>上传附件</H>
        <P>
          点输入框的回形针图标上传文件随问题一起发送。附件上传前需要先绑定年审项目。
        </P>
        <H>流式回复与思考面板</H>
        <P>
          AI 回复是流式输出的。回复上方的「思考」面板会展示 AI 正在执行的步骤
          （归一化输入、检索记忆、生成报告…）。在「设置」中开启「显示节点跟踪」可看到更详细的节点 payload。
        </P>
        <Tip>
          让 AI「执行完整年审并生成报告」会触发全量分析，耗时可能较长，生成的报告带可点击的角标，
          用于证据追溯。
        </Tip>
      </>
    ),
  },
  {
    id: "evidence",
    title: "报告角标与证据追溯",
    icon: Quote,
    content: (
      <>
        <P>
          审计报告正文里的角标（如{" "}
          <span className="mx-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded bg-primary/15 px-1 text-[10px] font-semibold text-primary">
            1
          </span>
          ）都是可点击的。点击即可一路回溯到原始审计资料。
        </P>
        <H>操作流程</H>
        <ul className="space-y-2 text-sm">
          <Step n={1}>点击报告中的角标，右侧滑出「证据抽屉」。</Step>
          <Step n={2}>
            抽屉左侧是支撑该结论的证据列表（文件名 + 页码 + 引文），右侧是对应的审计资料页面。
          </Step>
          <Step n={3}>
            PDF / 图片类资料会渲染页面原图，并用蓝色高亮框标出证据所在位置；
            纯文本类资料展示引用的原文片段。
          </Step>
          <Step n={4}>用页面底部的「← / →」可翻看同一文件的相邻页。</Step>
        </ul>
        <Tip>
          报告顶部若出现「角标覆盖率偏低」的提示，说明部分关键结论尚未挂上证据，
          建议补充材料后重新生成报告。
        </Tip>
      </>
    ),
  },
  {
    id: "graph",
    title: "知识图谱",
    icon: Network,
    content: (
      <>
        <P>
          审计关系图谱把被审计单位、客户、供应商、银行账户、凭证、合同和关联方之间的关系
          （交易、收付款、控制、关联、凭证支撑）可视化成可交互网络图。
        </P>
        <H>打开图谱</H>
        <ul className="space-y-2 text-sm">
          <Step n={1}>
            在项目工作台点「查看图谱」，或在对话页工具栏点「图谱」按钮，打开全屏图谱。
          </Step>
          <Step n={2}>
            选定一个<b>中心实体</b>后，图谱会以它为中心展开关联网络。也可从证据抽屉的
            「在图谱中查看」进入，自动以该证据涉及的实体为中心。
          </Step>
        </ul>
        <H>探索图谱</H>
        <ul className="space-y-2 text-sm">
          <Step n={1}>
            节点颜色代表实体类型，边的粗细 / 透明度代表关系置信度，中心节点会放大高亮。
          </Step>
          <Step n={2}>
            点击<b>节点</b>，右侧面板显示实体类型与审计属性，可「以此为中心」重新展开。
          </Step>
          <Step n={3}>
            点击<b>边</b>，右侧面板显示这条关系背后的结论（claim）与支撑证据，
            点证据可直接打开证据抽屉看页图。
          </Step>
          <Step n={4}>
            顶部「深度」选择器（1 / 2 / 3）控制展开几跳关系；跳数越大节点越多。
          </Step>
        </ul>
        <Tip>节点过多时图谱会提示缩小深度或筛选关系类型，以保持可读性。</Tip>
      </>
    ),
  },
  {
    id: "governance",
    title: "年审项目工作台",
    icon: ClipboardCheck,
    content: (
      <>
        <P>
          项目工作台（年审项目列表点「项目工作台 →」进入）集中管理资料处理、审计结论变化、
          待补资料、审计调整和报告发布前校验。
        </P>
        <H>① 资料处理记录</H>
        <P>
          按时间线展示每一批审计资料的处理事件：批次名、资料类别、操作人、文件数，
          以及处理阶段（已存储 / OCR 中 / 图谱提取中 / 已完成 / 失败）。
          某批次若引发结论变化，会标出「↑ N 条结论变化」；失败的事件可展开查看错误原因。
        </P>
        <H>② 审计结论演进</H>
        <P>
          展示 AI 结论随新材料补入的变化：「新增」是全新结论，「替代」会左右对比旧结论
          （删除线）与新结论。可按类型筛选，并展开查看支撑证据。
        </P>
        <H>③ 待补资料</H>
        <P>
          列出因依赖缺失而暂时无法落地的关系 / 断言，并标明「缺哪些材料」。
          全部补齐时显示「✓ 全部依赖已补齐」。
        </P>
        <H>发布前验收</H>
        <P>
          审计报告定稿前，点头部「验收」按钮运行证据完整性卡口。
          全部角标通过才会亮起「✓ 可发布」；有失败则列出每条角标的具体问题。
        </P>
      </>
    ),
  },
  {
    id: "tips",
    title: "小贴士",
    icon: Lightbulb,
    content: (
      <>
        <H>高效使用</H>
        <ul className="space-y-2 text-sm">
          <Step n={1}>
            开始审计前，先用 <code className="rounded bg-muted px-1 py-0.5 text-xs">/case</code> 绑定年审项目，
            AI 才能基于该项目账套与资料回答。
          </Step>
          <Step n={2}>
            报告里看到不确定的结论，点角标回溯到原文是最快的核实方式。
          </Step>
          <Step n={3}>
            想厘清资金往来、客户供应商或关联方关系，用审计关系图谱比读文字更直观。
          </Step>
          <Step n={4}>
            报告定稿前，务必运行一次「验收」，确保关键结论都有可追溯证据。
          </Step>
        </ul>
        <H>遇到空白？</H>
        <P>
          若证据抽屉或图谱显示「暂无数据」，通常是该项目资料尚未完成证据切片或图谱提取，
          可到项目工作台确认处理状态，或补充相应资料后重试。
        </P>
      </>
    ),
  },
];
