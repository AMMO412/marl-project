#include <chrono>
#include <condition_variable>
#include <fstream>
#include <iostream>
#include <mutex>
#include <string>

#include <ignition/msgs/image.pb.h>
#include <ignition/transport/Node.hh>

namespace {
std::mutex Mutex;
std::condition_variable Ready;
bool Saved = false;
std::string OutputPath;

void OnImage(const ignition::msgs::Image &_image) {
  std::lock_guard<std::mutex> lock(Mutex);
  if (Saved)
    return;
  const auto expected = static_cast<size_t>(_image.width()) * _image.height() * 3;
  if (_image.data().size() != expected) {
    std::cerr << "Unexpected RGB byte count: " << _image.data().size()
              << ", expected " << expected << std::endl;
    return;
  }
  std::ofstream output(OutputPath, std::ios::binary);
  output << "P6\n" << _image.width() << " " << _image.height() << "\n255\n";
  output.write(_image.data().data(), static_cast<std::streamsize>(_image.data().size()));
  Saved = output.good();
  Ready.notify_one();
}
}  // namespace

int main(int argc, char **argv) {
  if (argc != 2) {
    std::cerr << "usage: save_ign_image OUTPUT.ppm" << std::endl;
    return 2;
  }
  OutputPath = argv[1];
  ignition::transport::Node node;
  if (!node.Subscribe("/overview/image", OnImage)) {
    std::cerr << "Unable to subscribe to /overview/image" << std::endl;
    return 3;
  }
  std::unique_lock<std::mutex> lock(Mutex);
  if (!Ready.wait_for(lock, std::chrono::seconds(60), [] { return Saved; })) {
    std::cerr << "Timed out waiting for overview image" << std::endl;
    return 4;
  }
  std::cout << OutputPath << std::endl;
  return 0;
}
