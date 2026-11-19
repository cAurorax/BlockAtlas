function request(path, method = "GET", data) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: getApp().globalData.baseUrl + "/api" + path,
      method,
      data,
      header: {
        Authorization: "Bearer " + wx.getStorageSync("token"),
        "Content-Type": "application/json",
      },
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300)
          return resolve(res.data);
        if (res.statusCode === 401 && !path.startsWith("/auth/login")) {
          wx.removeStorageSync("token");
          wx.reLaunch({ url: "/pages/login/login" });
        }
        reject(
          new Error(
            typeof res.data.detail === "string"
              ? res.data.detail
              : "输入格式有误，请检查内容",
          ),
        );
      },
      fail() {
        reject(new Error("无法连接服务，请检查服务器地址和网络"));
      },
    });
  });
}
function upload(path) {
  return new Promise((resolve, reject) =>
    wx.uploadFile({
      url: getApp().globalData.baseUrl + "/api/media",
      filePath: path,
      name: "file",
      header: { Authorization: "Bearer " + wx.getStorageSync("token") },
      success(res) {
        let data;
        try {
          data = JSON.parse(res.data);
        } catch (e) {
          return reject(new Error("上传响应异常"));
        }
        if (res.statusCode >= 200 && res.statusCode < 300) resolve(data);
        else reject(new Error(data.detail || "上传失败"));
      },
      fail() {
        reject(new Error("上传失败，请检查网络"));
      },
    }),
  );
}
function mediaUrl(url) {
  return (
    getApp().globalData.baseUrl +
    url +
    "?token=" +
    encodeURIComponent(wx.getStorageSync("token"))
  );
}
function decorate(post) {
  const d = new Date(new Date(post.created_at).getTime() + 8 * 3600 * 1000);
  return {
    ...post,
    initial: post.nickname.slice(0, 1),
    date: d.toISOString().replace("T", " ").slice(0, 16) + " 北京时间",
    visibilityLabel: { public: "公开", friends: "好友可见", private: "仅自己" }[
      post.visibility
    ],
    media: post.media.map((m) => ({ ...m, src: mediaUrl(m.url) })),
  };
}
function error(e) {
  wx.showToast({
    title: e.message || "操作失败",
    icon: "none",
    duration: 2500,
  });
}
function confirm(content) {
  return new Promise((resolve) =>
    wx.showModal({
      title: "请确认",
      content,
      success: (r) => resolve(r.confirm),
    }),
  );
}
module.exports = { request, upload, mediaUrl, decorate, error, confirm };
