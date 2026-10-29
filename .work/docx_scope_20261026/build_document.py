from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from docx import Document
from docx.shared import Cm, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

WORK = Path(__file__).resolve().parent
SOURCE = WORK / '机器人移动话题说明_编辑前.docx'
OUT = WORK / '机器人移动话题说明_整理稿.docx'
FONT = 'C:/Windows/Fonts/msyh.ttc'
BOLD = 'C:/Windows/Fonts/msyhbd.ttc'


def diagram(path, mode):
    im = Image.new('RGB', (1740, 480 if mode == 'scope' else 460), 'white')
    dr = ImageDraw.Draw(im)
    regular = ImageFont.truetype(FONT, 29)
    bold = ImageFont.truetype(BOLD, 32)
    def box(xy, title, desc, focus=False):
        dr.rounded_rectangle(xy, 15, fill='#EAF2FA' if focus else '#F4F6F8',
                             outline='#54769B' if focus else '#A9B4C0', width=3)
        x0,y0,x1,y1=xy
        dr.text(((x0+x1)/2, y0+40), title, font=bold, fill='black', anchor='mm')
        dr.text(((x0+x1)/2, y0+89), desc, font=regular, fill='#26333F', anchor='mm')
    def arrow(points, direction='right'):
        dr.line(points, fill='#647588', width=4)
        x,y=points[-1]
        if direction=='right': triangle=[(x,y),(x-15,y-8),(x-15,y+8)]
        elif direction=='left': triangle=[(x,y),(x+15,y-8),(x+15,y+8)]
        elif direction=='up': triangle=[(x,y),(x-8,y+15),(x+8,y+15)]
        else: triangle=[(x,y),(x-8,y-15),(x+8,y-15)]
        dr.polygon(triangle, fill='#647588')
    if mode=='scope':
        box((15,20,500,155),'上层编组模块','提供结构化编组与任务')
        box((625,20,1110,155),'我方中间任务规划','分解 分配 时序与条件',True)
        box((1235,20,1720,155),'下层单平台执行','接收执行并回传结果')
        arrow([(500,86),(625,86)])
        arrow([(1110,86),(1235,86)])
        arrow([(1465,155),(1465,235),(870,235),(870,155)],'up')
        dr.text((1140,205),'执行反馈与状态变化',font=regular,fill='#26333F',anchor='mm')
        box((1235,320,1720,455),'Gazebo 与 UE5 平台','仿真 显示与数据采集')
        arrow([(1570,155),(1570,320)],'down')
        dr.text((580,340),'任务计划与速度控制属于不同粒度',font=bold,fill='black',anchor='mm')
        dr.text((580,392),'执行接口 路径及底层控制责任仍待确认',font=regular,fill='#26333F',anchor='mm')
    else:
        box((15,20,500,155),'控制程序','发布当前速度要求')
        box((625,20,1110,155),'ROS 2 控制话题','geometry_msgs / Twist')
        box((1235,20,1720,155),'ros_gz_bridge','转换 ROS 与 Gazebo 消息')
        box((1235,295,1720,430),'Gazebo 插件与模型','执行速度并产生运动')
        box((625,295,1110,430),'位姿发布与桥接','回传位置和姿态')
        box((15,295,500,430),'反馈读取与 UE5','查看数据和显示运动')
        arrow([(500,86),(625,86)])
        arrow([(1110,86),(1235,86)])
        arrow([(1480,155),(1480,295)],'down')
        arrow([(1235,360),(1110,360)],'left')
        arrow([(625,360),(500,360)],'left')
    im.save(path)


doc = Document(SOURCE)
for child in list(doc.element.body):
    if child.tag != qn('w:sectPr'):
        doc.element.body.remove(child)
section = doc.sections[0]
section.page_width, section.page_height = Cm(21), Cm(29.7)
section.top_margin, section.bottom_margin = Cm(1.7), Cm(1.65)
section.left_margin = section.right_margin = Cm(2)
section.header_distance, section.footer_distance = Cm(0.7), Cm(0.75)
for name in ('Normal','Title','Subtitle','Heading 1','Heading 2'):
    if name not in doc.styles:
        doc.styles.add_style(name,WD_STYLE_TYPE.PARAGRAPH)
    st=doc.styles[name]
    st.font.name='Calibri'
    st.element.get_or_add_rPr().get_or_add_rFonts().set(qn('w:eastAsia'),'微软雅黑')
    st.font.color.rgb=RGBColor(0,0,0)
    st.font.italic=False
    st.font.underline=False
    st.paragraph_format.widow_control=True
    pp=st.element.find(qn('w:pPr'))
    if pp is not None:
        for el in list(pp):
            if el.tag in (qn('w:pBdr'),qn('w:shd')): pp.remove(el)
normal=doc.styles['Normal']
normal.font.size=Pt(10.5)
normal.paragraph_format.line_spacing=Pt(16)
normal.paragraph_format.space_after=Pt(6)
normal.paragraph_format.space_before=Pt(0)
for name,size in (('Title',24),('Subtitle',11),('Heading 1',16),('Heading 2',11.5)):
    st=doc.styles[name]
    st.font.size=Pt(size)
    st.font.bold=(name!='Subtitle')
    st.paragraph_format.space_before=Pt(10 if name=='Heading 2' else 0)
    st.paragraph_format.space_after=Pt(9 if name in ('Title','Heading 1') else 6)
    st.paragraph_format.keep_with_next=True
    st.paragraph_format.line_spacing=Pt(size+5)


def p(text, lead=None, size=None):
    para=doc.add_paragraph()
    if lead and text.startswith(lead):
        para.add_run(lead).bold=True
        para.add_run(text[len(lead):])
    else: para.add_run(text)
    if size:
        for run in para.runs: run.font.size=Pt(size)
    return para


def heading(text, new_page=False, level=1):
    para=doc.add_paragraph(text,style='Heading %d'%level)
    para.paragraph_format.page_break_before=new_page
    return para


def table(headers, rows, widths):
    t=doc.add_table(rows=1,cols=len(headers))
    t.alignment=WD_TABLE_ALIGNMENT.CENTER
    t.autofit=False
    for col,width in zip(t.columns,widths): col.width=Cm(width)
    pr=t._tbl.tblPr
    borders=OxmlElement('w:tblBorders')
    for side in ('top','left','bottom','right','insideH','insideV'):
        el=OxmlElement('w:'+side)
        el.set(qn('w:val'),'single');el.set(qn('w:sz'),'5');el.set(qn('w:color'),'D9D9D9')
        borders.append(el)
    pr.append(borders)
    repeat=OxmlElement('w:tblHeader');t.rows[0]._tr.get_or_add_trPr().append(repeat)
    for index,values in enumerate([headers]+rows):
        row=t.rows[0] if index==0 else t.add_row()
        no_split=OxmlElement('w:cantSplit');row._tr.get_or_add_trPr().append(no_split)
        for i,(cell,text,width) in enumerate(zip(row.cells,values,widths)):
            cell.width=Cm(width)
            cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
            tcpr=cell._tc.get_or_add_tcPr()
            shade=OxmlElement('w:shd');shade.set(qn('w:fill'),'E9EFF5' if index==0 else ('F7F9FB' if index%2==0 else 'FFFFFF'));tcpr.append(shade)
            margins=OxmlElement('w:tcMar')
            for side in ('top','left','bottom','right'):
                el=OxmlElement('w:'+side);el.set(qn('w:w'),'75' if side in ('top','bottom') else '95');el.set(qn('w:type'),'dxa');margins.append(el)
            tcpr.append(margins)
            cell.text=str(text)
            for para in cell.paragraphs:
                para.paragraph_format.space_after=Pt(0)
                para.paragraph_format.space_before=Pt(0)
                para.paragraph_format.line_spacing=Pt(14)
                para.paragraph_format.keep_with_next=False
                if i==0 and len(headers)==3: para.alignment=WD_ALIGN_PARAGRAPH.CENTER
                for run in para.runs:
                    run.font.size=Pt(9.5)
                    run.font.bold=index==0
                    run.font.color.rgb=RGBColor(0,0,0)
    doc.add_paragraph().paragraph_format.space_after=Pt(0)
    return t


def fig(filename, caption):
    para=doc.add_paragraph()
    para.alignment=WD_ALIGN_PARAGRAPH.CENTER
    para.paragraph_format.keep_with_next=True
    para.paragraph_format.line_spacing=1.0
    para.add_run().add_picture(str(WORK/filename),width=Cm(17))
    para.paragraph_format.space_after=Pt(3)
    cap=p(caption,size=9)
    cap.alignment=WD_ALIGN_PARAGRAPH.CENTER
    cap.paragraph_format.space_after=Pt(8)


def question(code,title,body,evidence=None):
    heading(code+' '+title,level=2)
    p(body)
    if evidence:
        para=p('依据与缺口  '+evidence,size=9)
        para.paragraph_format.space_after=Pt(6)


diagram(WORK/'scope-flow.png','scope')
diagram(WORK/'movement-flow.png','movement')

# Page 1
doc.add_paragraph('机器人移动话题说明',style='Title')
doc.add_paragraph('完整流程 中间层职责及待沟通事项',style='Subtitle')
p('整理日期  2026年10月26日    用途  后续接口与责任沟通',size=9)
p('当前判断：我方负责从结构化编组和任务输入，到任务分解、分配、时序及条件安排，再到下发、反馈处理和重规划。任务规划可以包含到位后的活动编排；具体输出到任务、路线还是控制指令，现有会议记录尚未定清。',lead='当前判断：')
p('本说明把会议依据、当前移动接口和待确认边界分开记录，供下一轮沟通使用。下文的建议不代表已经确认的分工、实现结果或需求变更。')
heading('一 完整流程怎样衔接')
fig('scope-flow.png','图1 三层业务分工与仿真平台的位置')
for lead,text in [
('1 接收输入  ','接收上层编组、成员、能力、约束和任务等信息，理解字段、坐标、时间及版本。'),
('2 形成计划  ','把任务要求组织为子任务，确定执行对象、先后顺序、时间安排和前置条件。'),
('3 下发与展示  ','把执行序列交给下层单平台模块，同时向平台侧提供可显示的计划数据。'),
('4 执行与回传  ','下层落实任务并回传状态、进度或结果；Gazebo及其插件提供模型运动和仿真过程。'),
('5 判定与重规划  ','中间层依据有效反馈发现偏差，结合上层成员变化重新安排；阈值与结果语义须约定。'),
('6 留痕与复盘  ','关联输入、计划、执行记录和判定依据；未来计划展示与历史轨迹回放分别处理。')]:
    p(lead+text,lead=lead)

# Page 2
heading('二 会议纪要能确认到哪里',True)
p('下表以用户提供的会议纪要条目与时间轴追溯。第一次为甲方沟通，第二次为团队内部讨论；两者的确定程度不同，不能把内部解释提升为甲方已确认的全部交付范围。')
table(['编号','会议出处','记录与边界含义'],[
('R1','会议一 第25至26项\n51:10—52:59','上层编组—中间规划—下层单平台执行。我方承担中间层并对接两端；会上称下层尚未完成，不能据此认为平台团队已提供完整执行模块。'),
('R2','会议一 第27至28项\n52:59—55:41','先做基础规则替代模块跑通执行反馈，再推进训练和正式对接。临时替身有会议依据，但替代到何种粒度、最终谁接收仍未明确。'),
('R3','会议一 第29至31项\n55:44—58:42','需解析想定与导调数据、输出可识别指令，并处理执行偏差与重规划。输入输出格式、失败、超时及偏差阈值当时没有定值。'),
('R4','会议一 第34至36项\n01:01:48—01:06:25','上层通知成员变化，我方重规划；开发方拟任务草案并交专家评审。续航、载荷为阶段重点，不代表其他正式要求自动取消。'),
('R5','会议一 第40至43项\n01:12:32—01:17:00','执行序列发给下层并供平台展示；未来计划与历史回放不同。未来步数只举10或20步，步长、频率和反馈格式未定。'),
('R6','会议二 第6及8至9项\n08:22—11:15','内部认为不负责底层运动实现，并重申中间层位置；10/20步指未来步骤与动作安排。属于内部理解，不足以最终确定路径及控制接口归属。'),
('R7','会议二 第13项\n13:14—15:39','内部说明任务规划不只是路径，还包括到达后的执行内容、顺序与过程活动；具体动作由谁细化和执行仍需甲方确认。')
],[1.3,4.3,11.4])
p('能确认的主线：我方不仅做工单分配，还负责计划的形成、下发和反馈闭环。R1、R3、R5共同支持这一职责。',lead='能确认的主线：')
p('仍不能直接下结论：会议没有说明我方必须输出逐拍速度，也没有说明下层必然接收目标点或完整动作序列。路径规划、任务执行接口和细粒度控制之间仍有空白。',lead='仍不能直接下结论：')

# Page 3
heading('三 当前移动接口能做到什么',True)
p('原Word中的链路图和模块表说明的是运动消息通道。下面按同一关系重排，补充它与任务级计划的差别。接口事实依据项目内《机器人移动话题说明.md》，不代表本次已进行联调。')
fig('movement-flow.png','图2 速度命令进入仿真以及位姿回传的链路')
table(['模块','在链路中的作用','不能据此认定的能力'],[
('控制程序','向指定机器人发布当前速度要求','自动理解高层任务或形成路线'),
('ROS 2','在运行程序之间传递消息','接收端已实际执行或完成任务'),
('ros_gz_bridge','转换ROS与Gazebo两侧消息','提供导航、任务编排或执行判据'),
('Gazebo控制插件','接收速度并驱动模型运动','真实履带、气动、飞控或性能已实现'),
('位姿反馈','回传模型的位置和姿态','返回完整任务状态、成果或电量'),
('UE5','接收位姿用于画面显示','暂停显示等于暂停Gazebo')
],[3.2,6.8,7.0])
p('已说明的接口：50台均使用 /rover_XX/cmd_vel；UGV为01–20，TANK为21–30，PLANE为31–40，WING为41–50。控制消息为Twist，位姿通道为 /model/rover_XX/pose，类型为TFMessage。',lead='已说明的接口：')
p('Twist表达速度：linear.x前后、angular.z偏航，飞机代理另支持linear.z升降。消息没有目标点、任务ID、持续时间或Header；位姿frame中还有私有延迟元数据。指令送达、模型运动、任务成功必须分开判断。',lead='Twist表达速度：')
p('接口空缺：当前没有自动到点、航线、避障、任务接收与取消确认、完整成果反馈。不能把“已有50路移动话题”解释成“下层任务执行智能体已经完成”。',lead='接口空缺：')
p('联调还须区分墙钟与仿真时间、示例速度与实际限值、停止发布与实际停止。20 Hz发令不证明同步精度；现有说明也没有独立命令超时停车。')

# Page 4
heading('四 我们大概负责到哪一步',True)
p('以下按会议证据划分责任方向。其中“会议依据较明确”不表示当前代码已经实现；“待确认”也不代表可以默认由我方或平台侧承担。')
table(['事项','当前边界判断','依据与需要补齐的内容'],[
('上层输入适配','我方接收与解释；上层提供样例','R1、R3；编组树含义、约束字段、事件版本仍需样例。'),
('任务分解与分配','我方中间层职责','R1、R7；不能只理解为把现成任务分给谁。'),
('时序 条件与活动安排','我方形成任务级计划；细化粒度待确认','R5、R7；到位后活动如何描述、谁提供可执行功能清单需确认。'),
('反馈判定与重规划','我方处理有效反馈；结果和事件来源双方约定','R3、R4；任务成果、失联、失败与超时的产生者不能混同。'),
('计划数据与复盘','我方提供计划及相关记录；平台侧承担显示采集','R5；未来计划和历史轨迹分开，具体数据与界面分工需确认。'),
('路径 航点与避障','归属未定','R6只是内部理解；不能推断已有导航或由我方包办。'),
('单平台任务执行模块','会议定义为下层；负责人及接口未落实','R1、R2；须区别正式执行模块与临时规则替身。'),
('Gazebo UE5与物理控制','平台侧建设；我方负责约定的对接','会议一第1、14、43项；不能自动把平台团队等同下层执行团队。')
],[4.0,6.1,6.9])
heading('本阶段建议先形成的产物',level=2)
p('按用户当前阶段目标，先交一版能解释、能复现的规则流程，不以一次性完成全部指标作为启动条件。以下是沟通建议，尚不是会议已经批准的阶段验收清单。')
for text in [
'1 一组上下游输入输出样例，逐项标明来源、单位、版本和责任人。',
'2 一份任务级计划样例，能说明子任务、对象、顺序、条件和预计时间；不预先扩大到底层控制。',
'3 一条独立反馈驱动的闭环，用普通仿真任务展示成功、失败、延迟与重新安排，并保留记录。',
'4 临时执行替身的替换边界及真实对接清单，明确哪些来自模拟、哪些来自正式模块。']:
    p(text)
p('已有工位演示只验证简单分配与消息闭环，不能作为空间移动、完整任务分解或真实接口完成的证据。',lead='已有工位演示')

# Page 5
heading('五 优先确认影响分工的五个问题',True)
p('这些问题会直接改变模块边界。建议先取得具体样例和责任结论，再继续扩大实现；不要求先补齐所有参数或性能数字。')
question('Q01','我们最终向下输出到哪个粒度',
         '请明确交付的是任务描述与时序、目标点与活动序列、航点路线，还是逐拍控制指令。希望拿到一份真实下发样例，并写明每个字段由哪层生成、哪层消费。',
         'R1与R5明确下发给单平台执行，但没有给出消息样例或最终粒度。')
question('Q02','单平台任务执行模块由谁提供',
         '请确认下层执行模块的团队、接口人、可用时间和现有功能。当前若仍只有速度话题，任务要求到速度控制之间由谁补齐；我方是否只做临时替身，替换和移交由谁负责。',
         'R1称下层尚未完成，R2允许规则替代；平台团队和执行团队不能自动视为同一方。')
question('Q03','路径规划与避障是否属于我们',
         '请分别确定路线生成、局部避障与运动跟踪的负责人，并说明我方需要读取哪些地图、障碍与位姿数据。若要求我方输出路线，应单列其输入、输出与验证范围。',
         'R6“不负责底层运动”属于内部理解，不能独自确定全部路径工作归属。')
question('Q04','到位后的活动由哪层细化',
         '我方是描述任务目的与执行条件，还是负责选取并排列下层已有活动？请由执行模块提供当前可用活动及接收、取消、结束反馈样例，明确不支持时怎样返回。',
         'R7说明规划超出路径，但具体活动粒度和执行接口仍须确认。')
question('Q05','谁给出任务成功或失败的事实',
         '请区分到位、执行结束、成果形成和结果确认，明确各类记录的产生模块、任务关联方式与最终判据确认人。尤其要说明缺反馈、到期未确认、取消和重试如何结算。',
         'R3阈值未定，R4要求任务草案评审；位姿接口不能代替完整结果反馈。')

# Page 6
heading('六 其余接口与阶段问题',True)
question('Q06','上层到底提供哪些完整输入',
         '请提供一份编组、任务、能力和约束样例；说明编组树节点含义、硬约束与偏好、地图及事件可见范围。需明确成员变化由上层通知，还是我方也负责原始状态监测。')
question('Q07','未来多步计划的时间语义是什么',
         '请确认一步代表时间片、子任务还是动作，以及步长、更新频率和新旧计划切换方式。10/20步是会上举例，不能直接写成固定要求。')
question('Q08','平台身份与参数以哪份配置为准',
         '请提供权威roster，核对逻辑ID、模型ID、类型与话题；区分公开参考、已配置限值和验证值。示例速度不能当上限，未知续航和载荷不自动补值。')
question('Q09','失败 失联 取消与恢复怎样对齐',
         '请明确各状态由谁产生、何时生效、何时允许重新分配，以及恢复接入后是否继承旧任务。临时替身的噪声和失败不能与真实反馈混写。')
question('Q10','展示 采集与评估如何分工',
         '请区分我方计划数据输出、平台显示、历史轨迹采集、指标计算与报告生成。未来计划和历史执行用何种标识关联，同一事件时间戳怎样对齐。')
question('Q11','规则阶段的最小通过条件是什么',
         '建议现场选定普通演示场景、输入输出样例、异常用例和留痕要求，并列清本阶段暂缓项。先交规则版本不代表正式学习与其他需求自动取消。')
question('Q12','接口确认和变更由谁闭环',
         '请落实上下游接口人、样例交付时间、版本管理和联调环境；约定变更如何通知与复核，避免以“加一个解析函数即可”的估计替代实际测试。')
heading('沟通后希望取得的四项材料',level=2)
p('一份确认后的职责表；上下游各一份真实样例；一份下层执行能力与反馈清单；一份规则阶段范围和通过条件。未决定的事项保留“待确认”，不默认归属。')
heading('依据与追溯',level=2)
p('主要依据：Obsidian《会议纪要_甲方需求沟通与团队内部讨论》；纪要整理日期为2026-10-20，时间轴与条目见第二页R1—R7。',size=9)
p('接口依据：项目内《机器人移动话题说明.md》及本次桌面Word中的链路图和模块表。原Word已在编辑前另存副本。本文只解释流程与责任，不制定具体业务行动规则。',size=9)

footer=section.footer.paragraphs[0]
footer.alignment=WD_ALIGN_PARAGRAPH.CENTER
footer.paragraph_format.space_after=Pt(0)
for text,field in [('第 ',None),('', 'PAGE'),(' 页 共 ',None),('', 'NUMPAGES'),(' 页',None)]:
    run=footer.add_run(text);run.font.size=Pt(9)
    if field:
        begin=OxmlElement('w:fldChar');begin.set(qn('w:fldCharType'),'begin')
        instr=OxmlElement('w:instrText');instr.set(qn('xml:space'),'preserve');instr.text=' '+field+' '
        end=OxmlElement('w:fldChar');end.set(qn('w:fldCharType'),'end')
        run._r.extend([begin,instr,end])
doc.core_properties.title='机器人移动话题说明与任务规划中间层职责'
doc.core_properties.subject='完整流程 会议依据 职责边界 待沟通问题'
doc.core_properties.author=''
doc.core_properties.last_modified_by=''
doc.save(OUT)
print(OUT)

