App({
  globalData: { baseUrl: "http://127.0.0.1:18182", user: null },
  onLaunch() {
    this.globalData.user = wx.getStorageSync("user") || null;
  },
});
