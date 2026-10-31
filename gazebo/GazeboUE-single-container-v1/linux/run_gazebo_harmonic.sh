#!/usr/bin/env bash
set -eo pipefail
source /opt/ros/jazzy/setup.bash
cd "$(dirname "$0")"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-118}"
export ROS_LOCALHOST_ONLY=1
: "${GAZEBO_INSTANCE_ID:=container_00}"
: "${GZ_PARTITION:=wangdazhe_${GAZEBO_INSTANCE_ID}}"
: "${GAZEBO_UE_RUNTIME_DIR:=/opt/gazebo_ue/runtime}"
export GZ_PARTITION GAZEBO_INSTANCE_ID GAZEBO_UE_RUNTIME_DIR
mkdir -p "$GAZEBO_UE_RUNTIME_DIR"

python3 prepare_scene.py
sensor_count=$(python3 -c "import xml.etree.ElementTree as E; print(len(E.parse('rover_ue.sdf').findall('.//sensor')))" )
echo "GAZEBO_UE_ARCHITECTURE ros=jazzy gazebo=harmonic physics=Gazebo rendering=UE sensors=$sensor_count"
setsid gz sim -s -r rover_ue.sdf > "$GAZEBO_UE_RUNTIME_DIR/gazebo.log" 2>&1 &
sim_pid=$!

pose_topic_count=0
for _ in $(seq 1 180); do
 pose_topic_count=$(gz topic -l 2>/dev/null | grep -Ec '^/model/robot_[0-9]{3}/pose$' || true)
 if [ "$pose_topic_count" -eq 50 ]; then
  break
 fi
 sleep 0.5
done
if [ "$pose_topic_count" -ne 50 ]; then
 echo "Expected 50 Gazebo pose topics, found $pose_topic_count" >&2
 kill -TERM -- "-$sim_pid" 2>/dev/null || true
 wait "$sim_pid" 2>/dev/null || true
 exit 1
fi

args=()
for i in $(seq -w 001 050); do
 args+=("/model/robot_${i}/pose@tf2_msgs/msg/TFMessage[gz.msgs.Pose_V")
 args+=("/robot_${i}/cmd_vel@geometry_msgs/msg/Twist]gz.msgs.Twist")
done
setsid ros2 run ros_gz_bridge parameter_bridge "${args[@]}" > "$GAZEBO_UE_RUNTIME_DIR/bridge.log" 2>&1 &
bridge_pid=$!
cleanup() {
 kill -TERM -- "-$sim_pid" "-$bridge_pid" 2>/dev/null || true
 wait "$sim_pid" "$bridge_pid" 2>/dev/null || true
}
trap cleanup EXIT
python3 pose_server.py
