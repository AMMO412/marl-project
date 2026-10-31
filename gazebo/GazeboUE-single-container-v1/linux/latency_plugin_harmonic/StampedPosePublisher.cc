// Source-side measurement: timestamp each model pose immediately before publish.
#include <chrono>
#include <cstdlib>
#include <string>
#include <time.h>
#include <gz/sim/System.hh>
#include <gz/sim/components/Pose.hh>
#include <gz/sim/components/Name.hh>
#include <gz/transport/Node.hh>
#include <gz/msgs/pose_v.pb.h>
#include <gz/msgs/Utility.hh>
#include <gz/plugin/Register.hh>

class StampedPosePublisher : public gz::sim::System,
 public gz::sim::ISystemConfigure, public gz::sim::ISystemPostUpdate {
 gz::sim::Entity entity;
 gz::transport::Node node;
 gz::transport::Node::Publisher publisher;
 std::string name;
 std::string instanceId{"container_00"};
 std::chrono::steady_clock::duration last{};
 uint64_t sequence=0;
 public:
 void Configure(const gz::sim::Entity &e,const std::shared_ptr<const sdf::Element>&,
  gz::sim::EntityComponentManager &ecm,gz::sim::EventManager&) override {
  entity=e; name=ecm.Component<gz::sim::components::Name>(e)->Data();
  if(const char *configured=std::getenv("GAZEBO_INSTANCE_ID"))instanceId=configured;
  publisher=node.Advertise<gz::msgs::Pose_V>("/model/"+name+"/pose");
 }
 void PostUpdate(const gz::sim::UpdateInfo &info,const gz::sim::EntityComponentManager &ecm) override {
  if(info.paused)return;
  if(info.simTime<last){last={};sequence=0;}
  if(sequence && info.simTime-last<std::chrono::nanoseconds(33333333))return;
  last=info.simTime;
  auto component=ecm.Component<gz::sim::components::Pose>(entity);
  if(!component)return;
  gz::msgs::Pose_V message;auto *p=message.add_pose();p->set_name(name);
  gz::msgs::Set(p->mutable_position(),component->Data().Pos());
  gz::msgs::Set(p->mutable_orientation(),component->Data().Rot());
  const auto sim=std::chrono::duration_cast<std::chrono::nanoseconds>(info.simTime).count();
  auto *stamp=p->mutable_header()->mutable_stamp();stamp->set_sec(sim/1000000000);stamp->set_nsec(sim%1000000000);
  auto *child=p->mutable_header()->add_data();child->set_key("child_frame_id");child->add_value(name);
  auto *frame=p->mutable_header()->add_data();frame->set_key("frame_id");
  const auto source=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::system_clock::now().time_since_epoch()).count();
  timespec raw;clock_gettime(CLOCK_MONOTONIC_RAW,&raw);
  const int64_t rawNs=int64_t(raw.tv_sec)*1000000000+raw.tv_nsec;
  frame->add_value(instanceId+"|"+std::to_string(source)+"|"+std::to_string(++sequence)+"|"+std::to_string(rawNs));
  publisher.Publish(message);
 }
};

GZ_ADD_PLUGIN(StampedPosePublisher, gz::sim::System,
 StampedPosePublisher::ISystemConfigure, StampedPosePublisher::ISystemPostUpdate)
