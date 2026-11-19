const api = require("../../utils/api");
Page({
  mine(){wx.navigateTo({url:'/pages/feed/feed?scope=mine'})},settings(){this.setData({settingsOpen:!this.data.settingsOpen})},
  data: {
    user: null,
    old_password: "",
    new_password: "",
    confirm: "",
    busy: false,
  },
  onShow() {
    this.setData({ user: getApp().globalData.user });
  },
  input(e) {
    this.setData({ [e.currentTarget.dataset.key]: e.detail.value });
  },
  async save() {
    if (this.data.busy) return;
    if (this.data.new_password !== this.data.confirm) {
      api.error(new Error("两次输入的新密码不一致"));
      return;
    }
    this.setData({ busy: true });
    try {
      await api.request("/auth/password", "PUT", {
        old_password: this.data.old_password,
        new_password: this.data.new_password,
      });
      this.clear();
      wx.showToast({ title: "请用新密码登录", icon: "none" });
    } catch (e) {
      api.error(e);
    } finally {
      this.setData({ busy: false });
    }
  },
  clear() {
    wx.removeStorageSync("token");
    wx.removeStorageSync("user");
    getApp().globalData.user = null;
    wx.reLaunch({ url: "/pages/login/login" });
  },
  async logout() {
    try {
      await api.request("/auth/logout", "POST");
    } catch (e) {}
    this.clear();
  },
});
