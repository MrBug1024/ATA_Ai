"use client";

import {
  Rocket,
  Scale,
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
          AI Hunter 是一个面向破产 / 不良资产业务的 AI 辅助文档分析平台。你可以上传卷宗，
          让 AI 生成审计报告，并从报告的每一条结论一路追溯到原始证据。
        </P>
        <H>左侧导航</H>
        <ul className="space-y-2 text-sm">
          <Step n={1}>
            <b>新建对话</b> —— 直接向 AI 提问，或选定一个案件做专项分析。
          </Step>
          <Step n={2}>
            <b>案件列表</b> —— 查看所有案件的风险评分、上传材料、进入案件治理中心。
          </Step>
          <Step n={3}>
            <b>最近对话</b> —— 历史会话随时可回看，标「案件」的对话带案件上下文。
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
    title: "案件管理",
    icon: Scale,
    content: (
      <>
        <P>「案件列表」是所有业务的起点。每一行是一个案件，展示风险评分与卷宗处理状态。</P>
        <H>风险评分</H>
        <P>
          综合风险分（0–100）由四个维度合成：轧差审计、瑕疵挤水、时效预警、行为扫描。
          分数越高风险越大，颜色越红。
        </P>
        <H>常用操作</H>
        <ul className="space-y-2 text-sm">
          <Step n={1}>
            <b>创建案件</b> —— 右上角按钮新建案件。
          </Step>
          <Step n={2}>
            <b>添加材料</b> —— 每行的「添加材料」按钮上传卷宗，选择文档类别后由后端解析入库。
          </Step>
          <Step n={3}>
            <b>治理 →</b> —— 每行末尾的链接进入「案件治理中心」（详见「案件治理」章节）。
          </Step>
        </ul>
        <Tip>卷宗上传后会异步处理（OCR → 抽取 → 入库），可在治理中心的「材料事件」里追踪进度。</Tip>
      </>
    ),
  },
  {
    id: "chat",
    title: "AI 对话与审计",
    icon: MessageSquare,
    content: (
      <>
        <P>对话是与 AI 交互的主入口。可以闲聊式提问，也可以绑定案件做完整审计。</P>
        <H>绑定案件</H>
        <P>
          在输入框输入 <code className="rounded bg-muted px-1 py-0.5 text-xs">/case</code>{" "}
          会弹出案件选择器，选定后这段对话即带上案件上下文，AI 的回答会基于该案件的卷宗数据。
        </P>
        <H>上传附件</H>
        <P>
          点输入框的回形针图标上传文件随问题一起发送。注意：附件上传需要先绑定案件（从案件页进入对话）。
        </P>
        <H>流式回复与思考面板</H>
        <P>
          AI 回复是流式输出的。回复上方的「思考」面板会展示 AI 正在执行的步骤
          （归一化输入、检索记忆、生成报告…）。在「设置」中开启「显示节点跟踪」可看到更详细的节点 payload。
        </P>
        <Tip>
          让 AI「出具完整审计报告」会触发全量分析，耗时较长（数分钟），生成的报告带可点击的角标，
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
          ）都是可点击的。点击即可一路回溯到原始卷宗。
        </P>
        <H>操作流程</H>
        <ul className="space-y-2 text-sm">
          <Step n={1}>点击报告中的角标，右侧滑出「证据抽屉」。</Step>
          <Step n={2}>
            抽屉左侧是支撑该结论的证据列表（文件名 + 页码 + 引文），右侧是对应的卷宗页面。
          </Step>
          <Step n={3}>
            PDF / 图片类卷宗会渲染页面原图，并用蓝色高亮框标出证据所在位置；
            纯文本类卷宗只展示引用的原文片段。
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
          知识图谱把案件里的实体（公司 / 个人 / 矿权 / 法院…）和它们之间的关系
          （担保 / 出资 / 关联…）可视化成一张可交互的网络图。
        </P>
        <H>打开图谱</H>
        <ul className="space-y-2 text-sm">
          <Step n={1}>
            在案件治理中心点「查看图谱」，或在对话页工具栏点「图谱」按钮，打开全屏图谱。
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
            点击<b>节点</b>，右侧面板显示该实体的类型与风险等级，可「以此为中心」重新展开。
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
    title: "案件治理",
    icon: ClipboardCheck,
    content: (
      <>
        <P>
          案件治理中心（案件列表点「治理 →」进入）面向操作员 / 管理员，
          集中管理一个案件的材料处理、结论变化与发布前校验。顶部有三个标签页。
        </P>
        <H>① 材料事件</H>
        <P>
          按时间线展示每一批卷宗的处理事件：批次名、文档类别、操作人、文件数，
          以及处理阶段（已存储 / OCR 中 / 图谱提取中 / 已完成 / 失败）。
          某批次若引发结论变化，会标出「↑ N 条结论变化」；失败的事件可展开查看错误原因。
        </P>
        <H>② 结论演进</H>
        <P>
          展示 AI 结论随新材料补入的变化：「新增」是全新结论，「替代」会左右对比旧结论
          （删除线）与新结论。可按类型筛选，并展开查看支撑证据。
        </P>
        <H>③ 未决补件</H>
        <P>
          列出因依赖缺失而暂时无法落地的关系 / 断言，并标明「缺哪些材料」。
          全部补齐时显示「✓ 全部依赖已补齐」。
        </P>
        <H>发布前验收</H>
        <P>
          标杆案件对外发布前，点头部「验收」按钮跑一次卡口校验。
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
            做案件分析时，先在对话里用 <code className="rounded bg-muted px-1 py-0.5 text-xs">/case</code> 绑定案件，
            AI 才能基于卷宗回答。
          </Step>
          <Step n={2}>
            报告里看到不确定的结论，点角标回溯到原文是最快的核实方式。
          </Step>
          <Step n={3}>
            想厘清复杂的担保 / 关联关系，用知识图谱比读文字更直观。
          </Step>
          <Step n={4}>
            发布标杆案件前，务必在治理中心跑一次「验收」确保所有结论都挂了证据。
          </Step>
        </ul>
        <H>遇到空白？</H>
        <P>
          若证据抽屉或图谱显示「暂无数据」，通常是该案件的卷宗尚未完成图谱提取，
          可到治理中心「材料事件」确认处理是否完成，或补充相应材料后重试。
        </P>
      </>
    ),
  },
];
