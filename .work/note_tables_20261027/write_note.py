import sys, json, hashlib, re, subprocess
from pathlib import Path
from dataclasses import asdict
sys.stdout.reconfigure(encoding='utf-8')
project=Path('C:/Users/ammo/Desktop/MARL项目')
code=project/'planning_middle_demo'
sys.path.insert(0,str(code))
import fleet, contracts_v2 as contracts, planner_v2 as planner
from trajectory_v2 import build_replay_data
from motion import DriveGains
vault=Path('D:/obsidianNOTE/ammo')
rel=Path('10_项目/MARL/参考_planning_middle_demo场景输入参数变量与输出总表.md')
target=vault/rel
if target.exists():
    raise RuntimeError('目标新笔记已存在，停止以避免覆盖')
status=subprocess.check_output(['git','-C',str(vault),'status','--short','--',rel.as_posix()],encoding='utf-8')
assert not status.strip()
originals={p:p.read_bytes() for p in [vault/'10_项目/MARL/实操_任务规划中间层规划能力版v2.md',vault/'10_项目/MARL/00_项目入口.md']}
run=code/'outputs/run_20261027_retest_163920_763952'
s=json.loads((run/'scenario.json').read_text(encoding='utf-8'))
r=json.loads((run/'report.json').read_text(encoding='utf-8'))
m=json.loads((run/'manifest.json').read_text(encoding='utf-8'))
trace=[json.loads(line) for line in (run/'trace.jsonl').read_text(encoding='utf-8').splitlines() if line]
replay=build_replay_data(s,r,trace)
raw_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in run.iterdir() if p.is_file()}
parts=[]
def add(text): parts.append(text.strip()+'\n')
def val(x):
    if x is None:return 'null'
    if isinstance(x,bool):return 'true' if x else 'false'
    if isinstance(x,(list,dict,tuple,set)):
        if isinstance(x,set):x=sorted(x)
        return json.dumps(x,ensure_ascii=False)
    return str(x)
def table(headers,rows):
    def cell(x):return val(x).replace('|','\\|').replace('\n','<br>')
    add('| '+' | '.join(map(cell,headers))+' |\n| '+' | '.join(['---']*len(headers))+' |\n'+'\n'.join('| '+' | '.join(map(cell,row))+' |' for row in rows))
def link(label,path):return f'[{label}]({Path(path).as_posix()})'

add('''---
type: reference
created: '2026-10-27'
updated: '2026-10-27'
cssclasses: [ammo-note]
---
# planning_middle_demo：场景、输入、参数、变量与输出总表

> [!abstract] 阅读结论
> 当前输入是场景 JSON、代码内能力/任务模板和运行参数；通过规则规划器与本地下层替身生成日志、指标与动态回放。城市场景的道路和地标来自公开 Gazebo 示例，平台部署和作业由演示设置，能力参数为暂定值。`motion=real` 仍为 Python 本地运动模拟，未连接 ROS/Gazebo，不是现实城市实测或完整五类任务行为仿真。

本表按 **2026-10-27 当前源码**与既有运行 `run_20261027_retest_163920_763952` 整理。覆盖用户可配置字段、主要业务变量和输出字段，不逐行罗列临时循环变量。数值是本次快照，不是最终交付参数。

阅读顺序：先看数据流与来源，再看输入和参数，最后查变量与输出。本次只整理笔记，没有重跑实验、训练模型或修改源码。

## 1. 数据流与文件职责''')
table(['阶段','实际读取或产生什么','主要文件'],[
['场景输入','平台编号与初始位置、作业类型与目标位置、H/K、来源元信息','scenarios/simple_city.json'],
['参数补全','按平台编号补类别和能力；按任务 type 补任务模板','fleet.py；contracts_v2.py'],
['规划','能力过滤、打分、指派、排程、冲突消解及校验','planner_v2.py'],
['协调','重规划、下发指令、核对反馈、维护状态','coordinator_v2.py'],
['本地下层替身','接收任务级指令、推进位置与抽象工作量、生成反馈','mock_fleet.py；motion.py'],
['运行导出','保存本轮输入、配置记录、日志、报告','run_demo_v2.py；reporting_v2.py'],
['回放','初始位置 + 已应用位置反馈 + 道路底图 → 自包含 HTML','trajectory_v2.py；trajectory_player.html']])
add('当前没有加载训练好的 MARL 策略权重；任务分配由规则规划器完成。回放中的移动是下层替身生成的位置反馈。')

add('## 2. 场景来源、坐标与单位')
table(['数据/量','本次内容','来源及证据边界'],[
['场景来源','OSRF citysim 的 simple_city.world','本地 scenario._meta 登记的公开仿真示例；不是现实城市测绘'],
['道路','11段道路折线，含 road_x_*、road_y_*、sandy_path','本地素材包 parsed/roads.csv；仅底图，不参与寻路'],
['平台初始位置','10台平台，四类','演示选择的部署点；各点 _src_xy_m 记录原始示例坐标'],
['作业目标位置','6个点，覆盖5种 type','人工设置的演示作业，选用场景既有地标'],
['x/y 变换','x=(x_m+110)×0.35；y=(y_m+137)×0.35','_meta.scale=0.35；offset_x=110；offset_y=137'],
['距离','位置、路程、位移使用场景单位','原始 x/y 几何可按上述变换反算；不能据此把速度、电量全部当实测量'],
['z / altitude','高度使用当前模拟的场景量纲','J3的30是代码模型目标值，不应直接称实测30米；未按x/y偏移换算z'],
['时间','仿真步','sim_s、*_s等字段名保留历史命名；t=46表示第46步，不等于测得46秒'],
['速度/角速度','场景单位/步；rad/步','代码运动模型的单位，不直接等于m/s或rad/s'],
['电量/载荷/工作量','演示量纲','battery不是百分比、Wh；payload不是已标定kg；work不是覆盖面积或实际效能'],
['传感器标签','eo / sar / ir','能力画像字符串，不代表已模拟传感器成像或真实数据采集']])
add('道路素材位置：'+link('roads.csv',project/'outputs/gazebo_assets_2026-10-26/parsed/roads.csv')+'。底图依赖在生成回放时读取，生成后的 HTML 内嵌道路；缺素材时回退网格，不能把带图成功视为已实现避障。')

add('## 3. 输入 JSON 字段')
table(['字段','类型/本次值','作用与消费位置'],[
['protocol','middle-demo/v2','协议版本；contracts_v2.check_scenario_v2校验'],
['objective','makespan','规划目标；可选makespan、energy、dispersion'],
['platforms','对象数组，10项','每项用robot_no和pos建Platform对象'],
['platforms[].robot_no','整数1～50','由编号推导pid、kind与话题；不可重复'],
['platforms[].pos','[x,y]','初始平面坐标；缺省时build_platforms使用(0,0)，本次均明确提供'],
['jobs','对象数组，6项','任务输入；job_id需唯一，pos必需'],
['jobs[].job_id','J1～J6','任务标识'],
['jobs[].type','patrol等5种类型之一','使用JOB_SPECS模板；当前校验不允许同时覆盖模板参数'],
['jobs[].pos','[x,y]','二维目标点'],
['无type的自定义任务字段','work/window/crew/need_payload，另有need_sensor/altitude','走custom分支；不与type模板覆盖混用'],
['H / K','35 / 8','未显式传--H/--K时由simulate读取'],
['rules','本次缺省，解析为{}','只接受max_attempts、grace_s、dev_threshold；覆盖传入simulate的同名参数'],
['timeline','本次缺省，解析为[]','可选实验事件时间线，见下表'],
['根级max_attempts/grace_s/dev_threshold','本次文件写了2/1/4.0','本入口未读取这些根字段作为覆盖值；本次与CLI默认恰好一致'],
['根级max_ticks','本次未写','即使校验允许，本入口仍使用CLI/函数入参，不从此根字段取值'],
['_meta','来源、坐标说明、scale/offset等','不参与规划决策；回放会用它对齐底图'],
['_src_xy_m / _src / _src_landmark','源坐标和地标文字','追溯与显示，不是额外路径规划输入']])
add('当前 `build_platforms` 的能力值全部取自 `fleet.PLANNING_PARAMS`；不能在每台平台 JSON 中随意覆盖 speed、battery 等私有能力。不要把“JSON有字段”与“入口确实消费了字段”混为一谈。')

table(['timeline.event','关键字段','含义/本次是否使用'],[
['member_lost','t、robot_no','指定仿真步通知成员失联；本次无'],
['job_fail','t、job_id','注入一次任务级失败；本次无'],
['job_delay','t、job_id、delay','顺延替身的arrival字段；不要直接推断real模式已经等效停驶；本次无'],
['job_slow','t、job_id、factor','factor在(0,1)，缩放工作量推进；本次无']])

add('## 4. 当前场景的10台平台')
table(['编号','pid / 类别','初始pos（场景单位）','原始_xy（示例米坐标）'],[
[p['robot_no'],f"{fleet.pid_of(p['robot_no'])} / {fleet.kind_of(p['robot_no'])}",p['pos'],p['_src_xy_m']] for p in s['platforms']])
add('编号映射为UGV=01～20、TANK=21～30、PLANE=31～40、WING=41～50；本次只选10台，不等于已运行50台。话题字段形如 `/rover_01/cmd_vel`、`/model/rover_01/pose`，当前只是消息中的接口信息，没有实际发布ROS消息。')

add('## 5. 平台能力参数（当前代码暂定值）')
table(['类别','speed','work_rate','初始battery','payload','sensor','can_climb'],[
[k]+[v[x] for x in ['speed','work_rate','battery','payload','sensor','can_climb']] for k,v in fleet.PLANNING_PARAMS.items()])
table(['字段','含义/单位','来源'],[
['speed','线速度上限，场景单位/步','fleet.PLANNING_PARAMS'],
['work_rate','每个到位成员每步贡献的抽象工作量','同上'],
['battery','初始电量，演示电量单位','同上；运行后随反馈更新'],
['payload','载荷能力，演示单位','同上；与need_payload比较'],
['sensor','传感器标签','同上；是否过滤还看ENABLED_CHECKS'],
['can_climb','是否允许模拟z方向运动','同上；不是完整飞机动力学能力'],
['move_cost','移动一规划步的电量模型系数','round(0.5×speed²,3)'],
['work_cost','作业一规划步的电量模型系数','round(1.0×work_rate²,3)']])
table(['类别','move_cost','work_cost'],[[k,v['move_cost'],v['work_cost']] for k,v in fleet.PLANNING_PARAMS.items()])
add('`config/platform_references.json` 是公开参考资料登记，当前不参与规划参数计算。替身在到达时一次记移动电、作业时逐步记作业电，因此报告电量不等于真实车辆能耗曲线。')

add('## 6. 当前6个任务及其模板值')
jobs=contracts.build_jobs(s)
table(['任务','type / 中文名','目标pos','已有地标'],[
[j['job_id'],j['type']+' / '+next(x['label'] for x in replay['jobs'] if x['job_id']==j['job_id']),j['pos'],j['_src_landmark'].split('（')[0]] for j in s['jobs']])
table(['任务','work','window（步）','crew','need_payload','need_sensor','altitude'],[
[j.job_id,j.work,list(j.window),j.crew,j.need_payload,j.need_sensor,j.altitude] for j in jobs])
add('本场景只写了type和pos，表中其余值由 `contracts_v2.JOB_SPECS` 补齐。`crew`是模板要求人数，`work`是抽象工作量，`window`是排程时间窗；它们不等于已经实现持续在位、覆盖回传或其他分类型任务完成判据。执行器没有按jtype切换行为，仍统一到点后累加工作量。')

add('## 7. 启动参数、默认值与本次取值')
table(['参数','不传时的默认','本次测试','说明'],[
['--scenario','scenarios/fleet_demo.json','scenarios/simple_city.json','默认是手编场景；城市场景需显式指定'],
['--mode','normal',m['mode'],'还可选failure/timeout/kill/deviation，属于故障演示模式'],
['--motion','teleport',m['motion'],'real表示本地逐步运动模拟'],
['--max-ticks',60,m['max_ticks'],'推进上限；提前settled可提前结束'],
['--H','None→场景H→缺省20',m['H'],'显式CLI值优先于场景'],
['--K','None→场景K→缺省5',m['K'],'重规划周期'],
['--max-attempts',2,m['max_attempts'],'包括第一次尝试，不是“额外重试2次”'],
['--grace-s',1,m['grace_s'],'超时容忍，当前按仿真步使用'],
['--dev-threshold',4.0,r['dev_threshold'],'进度落后阈值，工作量单位'],
['--out','outputs/run_时间戳目录',run.name,'输出目录必须不存在；本次显式指定独立目录'],
['--quiet',False,True,'仅减少控制台逐条日志；保存的trace/summary仍保留事件']])
add('参数优先级以当前入口为准：H/K是“显式CLI > 场景根字段 > 代码缺省”；三项rules参数则是“rules > 传入simulate的CLI/函数值”。manifest对三项规则仍可能记录CLI而非覆盖后生效值，不能对任意实验只看manifest推断有效配置。本次rules={}，没有这一覆盖冲突。`deviation`模式还会把等于4.0的阈值调整为2.0；本次normal没有该调整。')

add('## 8. 规则规划器的主要常量')
planner_rows=[
['RULE_VERSION',planner.RULE_VERSION,'规则版本标记'],
['ENABLED_CHECKS',planner.ENABLED_CHECKS,'当前只显式启用battery、payload过滤'],
['altitude检查','恒生效','有高度且不能爬升时拒绝，不依赖ENABLED_CHECKS'],
['sensor / motion检查','当前未在ENABLED_CHECKS中','有需求字段，不代表当前已执行该匹配检查'],
['KEEP_COMMITMENT',planner.KEEP_COMMITMENT,'滚动规划保留既有承诺'],
['URGENCY_FIRST',planner.URGENCY_FIRST,'截止时间优先开关'],
['URGENCY_WEIGHT',planner.URGENCY_WEIGHT,'紧迫度项权重'],
['SWAP_TO_FIT',planner.SWAP_TO_FIT,'排不进窗口时是否尝试换成员'],
['USE_HUNGARIAN',planner.USE_HUNGARIAN,'crew=1使用一对一最小代价求解'],
['BIG_COST',planner.BIG_COST,'不可行组合的有限大代价'],
['SPREAD_SCALE',planner.SPREAD_SCALE,'分散度项归一化尺度'],
['邻近计数半径',30.0,'拥挤代价项的场景距离阈值；不是物理安全距离']]
table(['名称','当前值','作用'],planner_rows)
table(['objective','time权重','energy权重','spread权重','crowd权重'],[
[k]+[v[x] for x in ['time','energy','spread','crowd']] for k,v in planner.COST_TERMS.items()])
add('以上为当前通用调度模型常量及代价项，不是已验证的最优参数；本次用makespan，不对另外两个目标给效果排名。')

add('## 9. 本地运动模拟参数')
g=asdict(DriveGains())
table(['名称','当前值/实际来源','含义与限制'],[
['max_linear','按类别speed取0.8/1.0/2.0/1.6','DriveGains裸默认1.0；实际指令motion_caps按平台速度补齐'],
['max_angular',g['max_angular'],'角速度上限，rad/步'],
['k_linear',g['k_linear'],'距离/高度误差的线速度比例系数'],
['k_angular',g['k_angular'],'航向误差比例系数'],
['tol_pos',g['tol_pos'],'水平距离与可爬升平台高度误差的到达容差，场景单位'],
['tol_yaw',g['tol_yaw'],'控制器转向对准阈值，rad；arrived本身不检查最终yaw'],
['TWIST_TICKS_PER_STEP',20,'每规划步内部积分20次；不是已测通信频率'],
['dt',0.05,'内部每拍为1/20规划步'],
['CMD_PERIOD_S',0.05,'代码中的发令周期常量；当前未连接ROS'],
['estimate_arrival_steps.max_steps',200,'规划用运动预演上限；与--max-ticks是不同参数'],
['linear.y / angular.x / angular.y',0,'当前简化运动模型固定为零'],
['初始yaw / z',0,'MockFleet平台状态初始化值，本场景没有输入初始朝向/高度']])
add('`GoalController`计算的是简化运动，固定翼/飞翼标签不代表已模拟完整气动或转弯约束；运动轨迹不自动沿道路，也不做建筑碰撞或避障。')

add('## 10. 主要变量字典')
add('### 10.1 标识、时间与计划')
table(['变量','所在对象/来源','含义'],[
['run_id','CoordinatorV2 / 消息 / report','本次为demo-v2；不是输出文件夹名，当前默认不会每轮自动变成唯一值'],
['plan_id','Plan / CoordinatorV2 / 消息','计划编号；内部计划与发消息计数有不同使用位置，不等于规划次数的统一编号证据'],
['job_id / worker_id / pid','Job / Command / Platform','任务ID；消息中的worker_id对应平台pid'],
['command_id','Command','格式run_id:job_id:attempt:pid；一台平台一次任务尝试的指令关联键'],
['event_id','反馈消息','反馈标识，替身形如fleet:1，用于去重'],
['attempt / attempts','Command / Job','单条命令尝试号 / 作业累计尝试数'],
['now / sim_s','模拟循环 / 日志或反馈','当前仿真步；不是墙钟时间'],
['created_at / horizon','Plan','生成计划时刻 / 规划视野H'],
['assignments / rejected','Plan','指派列表 / 不可行或被拒候选记录'],
['pids','Assignment','一项作业对应成员平台列表'],
['start / end','Assignment','real中start表示出发、end预计完工；teleport中start表示开工/瞬移时刻'],
['travel / dur','Assignment','预计在途步数 / 预计作业步数'],
['seq / coord','Assignment','序号与协调描述字段']])
add('### 10.2 平台与任务动态状态')
table(['变量','初始值/例子','含义'],[
['Platform.pos / yaw','输入pos / 0','当前位置/航向；由已消费反馈更新'],
['Platform.battery / alive','类别初始电量 / true','当前电量 / 是否存活'],
['Job.progress',0,'当前作业级抽象工作量，不是该成员自己的覆盖率'],
['Job.work / remain','模板work / max(0,work-progress)','总需求工作量 / 剩余工作量'],
['Job.status','pending','还可为assigned、running、cancelling、succeeded、failed'],
['Job.started_at','初始null','首次下发时固定的预计开工基准；不是实际到达时间戳'],
['Job.planned_end','初始null','首次下发预计完工基准，用于偏差检测'],
['active','command_id→Command','协调器当前活动指令集合'],
['platform_cmd / job_cmds','平台→指令 / 作业→指令列表','用于占用和关联'],
['seen / last_fb_time / cmd_progress','集合或字典','反馈去重 / 最近反馈时间 / 最近工作量'],
['pending / replan_log','待处理触发 / 历史触发','首次、周期、失联、失败、超时、偏差等来源'],
['audit / plan_traces','事件列表 / 规划留痕','导出trace及汇总统计的来源'],
['succeeded_at','job_id→仿真步','实际收到并接受成功反馈时记录的完成步'],
['MockFleet.platforms / jobs','替身自己的字典','独立下层状态，与协调器不共享对象'],
['charged','替身成员标志','表示已到达且记过移动电，不是电池充电状态'],
['arrival / travel_steps','替身成员字段','瞬移到达调度字段 / 移动电计费步数；不等于通用真实到达记录'],
['gained / done','每步推进 / 完成布尔','成员贡献之和 / 作业progress达到work']])
add('偏差中 `expect=work×(now-started_at)/max(1,planned_end-started_at)`，`lag=expect-progress`；lag超过阈值触发重规划。超时条件是 `now > expected_end_sim_s + grace_s`。这些是当前代码口径，并非任务业务验收判据。')

add('### 10.3 指令、任务块、投递块与反馈')
table(['层级/字段','含义','本次示例/约束'],[
['wire.protocol / run_id / plan_id / clock','外层身份与时钟口径','middle-demo/v2；demo-v2；demo_sim_steps'],
['command.action','指令动作','start或cancel'],
['issued_sim_s / start_sim_s / expected_end_sim_s','下发时刻 / 计划start / 预计结束','start_sim_s继承Assignment.start，需结合motion解释'],
['target_command_id','取消请求关联的原指令','只在取消路径使用'],
['task.jtype / position / altitude / goal','任务类型 / 平面目标 / 高度 / 目标位姿','goal包含x/y/z/yaw；yaw缺省0，不是实际最终朝向要求已被验证'],
['task.work / window / crew / members / window_deadline','工作量、时间窗、要求人数、成员、截止','任务级参数，不是分类型行为状态机'],
['delivery.pos / battery','下发时平台状态快照','下层首次见平台时用来初始化'],
['delivery.speed / work_rate / move_cost / work_cost','替身使用的能力和耗电参数','来自平台类别参数'],
['delivery.motion_caps / can_climb','运动上限、容差和爬升标志','当前给本地控制器使用'],
['cmd_vel_topic / pose_topic / stop_rule','接口字段 / 停止规则','只是声明，当前没有ROS通信'],
['feedback.status','指令反馈状态','accepted、progress、succeeded、failed、cancelled'],
['feedback.phase','推进阶段','travel、work或null；不要与status混用'],
['feedback.progress / pos / battery','作业级进度 / 平面位置 / 电量','进度4位小数、位置3位、电量2位'],
['feedback.z / yaw','高度与航向','本地real模式附加，z保留3位、yaw保留4位小数'],
['feedback.note','可选说明','失败或注入事件说明等']])
add('`trace.jsonl` 的一行是协调器审计记录；位置反馈位于 `kind=feedback_applied` 行内的 `event` 对象，并不是每行都有pos。完成反馈来自抽象作业进度，可能存在成员尚未到点的情况。')

add('### 10.4 回放变量与显示量')
table(['变量/显示项','来源/计算','解释'],[
['D','HTML内嵌replay-data JSON','包含workers/jobs/events/end/background；页面无需读取外部日志'],
['time / playing / selected','JavaScript播放器状态','当前回放仿真步 / 播放开关 / 选中平台pid'],
['samples','feedback_applied的位置序列','同平台同一sim_s保留最后条，再按时间排序'],
['start','scenario初始pos','无反馈时保持初始位置；不倒灌report最终位置'],
['distance（累计路程）','从初始位到各采样点逐段平面距离之和','不是直线位移；不含z；记录稀疏或四舍五入会影响精度'],
['displacement（起终点位移）','当前位置到初始pos的平面直线距离','即使路径往返很长，也可接近0'],
['距目标（平面）','当前位置到当前/最近任务pos的直线距离','不代表剩余可通行路径长度'],
['stateAt / sampleTime','当前时间最近反馈及可选显示插值','相邻逐步同指令的real记录间可插值；teleport和稀疏记录保持最近位置'],
['background.roads','坐标变换后的道路','只有匹配simple_city和素材可读时加载；仅显示'],
['1×播放','每墙钟秒播放2仿真步','播放速度不会改变已保存的实验结果'],
['电量—','无已知初始值且尚无反馈','表示未知；不从最终report倒推初始电量']])

add('## 11. 输出文件与本次证据')
add('本次完整目录：'+link(run.name,run)+'。')
table(['文件','内容','主要用途'],[
[link('scenario.json',run/'scenario.json'),'本轮输入JSON快照','核对平台/任务/来源字段；包含按原文件保存的字段，不代表每个字段都已消费'],
[link('manifest.json',run/'manifest.json'),'解释器、参数记录、输入文件哈希、backend等','追溯运行配置；仍需注意rules覆盖的记录差异'],
[link('trace.jsonl',run/'trace.jsonl'),'按行JSON审计事件','查实际下发、反馈、成功/失败及位置序列'],
[link('report.json',run/'report.json'),'最终作业/平台状态、指标和汇总','程序读取与核对指标'],
[link('summary.txt',run/'summary.txt'),'文本报告和事件','人读文本；--quiet不会使该文件只剩简要结果'],
[link('report.html',run/'report.html'),'作业表、指标、事件和输入展示','运行总览，含回放链接'],
[link('trajectory.html',run/'trajectory.html'),'自包含地图与播放器','查看实际反馈轨迹、时间轴和单台状态']])
add('另一个 `planning_middle_demo/outputs/simple_city_map.html` 由 `gen_map.py` 单独生成，展示初始规划示意，不是本轮实际执行轨迹；不能与本轮trajectory.html混用。')

add('### 11.1 report主要指标：公式与本次值')
table(['字段','本次值','代码口径'],[
['done',r['done'],'status=succeeded的任务数；分母为jobs长度6'],
['all_succeeded',r['all_succeeded'],'全部任务为succeeded'],
['settled',r['settled'],'全部任务进入succeeded或failed；不是“全部成功”的同义词'],
['simulated_until_s',r['simulated_until_s'],'最后推进到的仿真步，不是实际运行秒数'],
['makespan',r['makespan'],'成功任务完成步的最大值；仅有部分完成时也可能有值'],
['plans',r['plans'],'协调器计数的规划次数'],
['retries / timeouts',f"{r['retries']} / {r['timeouts']}",'sum(max(0,attempts-1)) / 审计中的timeout次数'],
['active_commands',r['active_commands'],'报告时活动命令数'],
['used_energy',r['used_energy'],'所有平台初始电量和−报告时剩余电量和；初始和为920'],
['per_task_energy',r['per_task_energy'],'used_energy/已完成任务数；无完成时null'],
['spread',r['spread'],'存活平台到其平面质心距离的均值，场景单位；不是任务覆盖率'],
['triggers',r['triggers'],'重规划触发来源计数，多个来源可出现在同轮'],
['need_report',r['need_report'],'曾需上报且最终仍未成功的任务ID'],
['solve_summary',r['solve_summary'],'一对一指派子问题的代价统计，不是全场景全局最优证明'],
['rejected_reasons',r['rejected_reasons'],'各轮候选拒绝累计次数；不是失败作业数量'],
['limit_reached',r['limit_reached'],'达到推进预算但尚未settled时为true'],
['mode / motion / H / K / rules / timeline',f"{r['mode']} / {r['motion']} / {r['H']} / {r['K']} / {{}} / []",'报告记录的本轮模式与有效部分配置']])

add('### 11.2 回放距离核对（终局）')
table(['平台','位置采样数','累计平面路程','起终点位移'],[
[w['pid'],len(w['samples']),f"{w['distance']:.2f}",f"{w['displacement']:.2f}"] for w in replay['workers']])
add(f"本轮trace共有 **{len(trace)}条**审计记录，其中 **{sum(x['kind']=='feedback_applied' for x in trace)}条**为feedback_applied。采样数不等于移动步数，无位置反馈的平台保留输入初始位置。")

add('## 12. 当前结果能说明什么')
table(['可据当前证据确认','不能据此推出'],[
['规则规划、消息替身和报告/回放可运行','已连接ROS/Gazebo/UE5或真实平台'],
['输入选用公开城市示例的坐标与道路','现实城市实测、沿道路规划或完整物理碰撞'],
['日志中6项抽象工作量达到完成阈值','五类任务的行为语义和业务完成判据全部达成'],
['记录了传感器与能力参数','所有能力匹配检查已启用或有真实传感器数据'],
['本轮文件夹独立保存','run_id/command_id已在跨轮通信中保证唯一隔离'],
['局部指派求解有最小代价结果','全场景任务规划达到全局最优']])
add('本轮的具体反例：`rover_02` 在t=45收到J4成功反馈时仍距目标约13.51场景单位。相关缺陷与现有责任判断见 [[实操_任务规划中间层规划能力版v2]]、[[审查_planning_middle_demo指标与系统可用性_2026-10-26]]；本表不变更模块分工，也不把问题记为已修复。')

add('## 13. 复现与来源')
add('在Windows PowerShell可执行以下命令；默认每次创建新输出目录，保留旧实验。只运行本地演示，不需要启动WSL或Gazebo：')
add('```powershell\npy -3.14 "'+(code/'run_demo_v2.py').as_posix()+'" --scenario "'+(code/'scenarios/simple_city.json').as_posix()+'" --motion real --max-ticks 200 --quiet\n```')
add('本次记录的Python版本为3.14.7；生成时间为 `'+m['generated_at']+'`；backend=`'+m['backend']+'`，external_integration_verified=`'+str(m['external_integration_verified']).lower()+'`。')
add('输入原文件SHA256（manifest登记）：`'+m['scenario_sha256']+'`。输出scenario.json因重新格式化，字节哈希不要求与原文件相同；不应据此误判内容被改。')
source_files=[('入口与参数优先级','run_demo_v2.py'),('编成与能力参数','fleet.py'),('输入校验与任务模板','contracts_v2.py'),('规划常量与计划变量','planner_v2.py'),('协调器状态与指标公式','coordinator_v2.py'),('本地模拟反馈与推进','mock_fleet.py'),('简化运动参数','motion.py'),('报告展示','reporting_v2.py'),('回放数据与底图转换','trajectory_v2.py'),('播放器状态与显示计算','trajectory_player.html')]
table(['核对内容','本地源码'],[[label,link(name,code/name)] for label,name in source_files])
add('相关：[[00_项目入口]] · [[实操_任务规划中间层规划能力版v2]] · [[调研_四类平台公开参数与Gazebo衔接]]。本笔记为独立新建，未向原实操笔记追加正文。')

content='\n'.join(parts)
# 新建专用模式防止同时出现的同名文件被覆盖。
with target.open('x',encoding='utf-8',newline='') as handle:handle.write(content)
readback=target.read_text(encoding='utf-8')
assert readback==content
assert all(p.read_bytes()==v for p,v in originals.items()),'原笔记出现变化，需复核'
assert all(hashlib.sha256((run/n).read_bytes()).hexdigest()==v for n,v in raw_hashes.items())
# 验证Markdown表格列数一致；对齐行必须紧跟表头。
rows=readback.splitlines(); table_count=0
for i,line in enumerate(rows):
    if line.startswith('| ') and i+1<len(rows) and rows[i+1].startswith('| ---'):
        table_count+=1
        count=len(re.split(r'(?<!\\)\|',line))
        j=i+1
        while j<len(rows) and rows[j].startswith('| '):
            assert len(re.split(r'(?<!\\)\|',rows[j]))==count,(j+1,rows[j])
            j+=1
for name in re.findall(r'\[\[([^\]|]+)',readback):
    assert (target.parent/(name+'.md')).exists(),name
receipt=dict(path=str(target),tables=table_count,lines=len(rows),chars=len(readback),original_notes_unchanged=True,run_files_unchanged=True,source_hashes={name:hashlib.sha256((code/name).read_bytes()).hexdigest() for _,name in source_files})
(project/'.work/note_tables_20261027/receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(receipt,ensure_ascii=False,indent=2))
print('\nREADBACK HEAD\n'+readback[:900])
print('\nREADBACK TAIL\n'+readback[-650:])
