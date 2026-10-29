# assets/city —— 本目录用到的真实场景素材

只保留 `city_nav.py` 解析障碍所需的**世界文件 + 显式盒体碰撞的模型 SDF**，
不含网格（DAE），因为网格碰撞不参与二维建图，也不臆造包围盒。

| 文件 | 来源 | SHA-256（前 16 位） |
| --- | --- | --- |
| `simple_city.world` | https://raw.githubusercontent.com/osrf/citysim/master/worlds/simple_city.world | `b36f8a3974f22643` |
| `models/salon/model.sdf` | https://raw.githubusercontent.com/osrf/gazebo_models/master/salon/model.sdf | `90ae5b8e8cd157f5` |
| `models/law_office/model.sdf` | https://raw.githubusercontent.com/osrf/gazebo_models/master/law_office/model.sdf | `3d39dbb3bf08b23d` |
| `models/thrift_shop/model.sdf` | https://raw.githubusercontent.com/osrf/gazebo_models/master/thrift_shop/model.sdf | `126c40248acbb08b` |
| `models/fire_station/model.sdf` | https://raw.githubusercontent.com/osrf/gazebo_models/master/fire_station/model.sdf | `1af64b55dc7501a3` |
| `models/police_station/model.sdf` | https://raw.githubusercontent.com/osrf/gazebo_models/master/police_station/model.sdf | `9043d259c5cbf392` |

完整哈希与下载日期见 `git log`/生成记录；本项目只把 SDF 的**盒体碰撞尺寸与位姿**
当作障碍几何，视觉网格、材质、贴图均未使用。

## 为什么只有 5 个模型

`simple_city.world` 引用了 500 多个对象（树、路灯、车辆、建筑等），但：

1. 本仓库只下载了少量模型的 SDF；
2. 多数建筑的 `collision` 是 `<mesh>`，没有可用的包围盒尺寸；
3. 因此 `city_nav.load_obstacles()` 只接纳**显式 `<box>` 碰撞**，其余对象计入
   `missing`/忽略，并在演示产物的「口径与局限」中写明。

需要扩大地图时，把对应模型的 `model.sdf` 放进 `models/<name>/`，保证其碰撞体
是盒体，再重跑 `behavior_demo.py` 即可——不需要改代码。
