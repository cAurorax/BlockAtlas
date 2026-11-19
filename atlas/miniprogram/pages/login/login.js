const api = require("../../utils/api");
Page({
  data: {
    register: false,
    username: "",
    password: "",
    nickname: "",
    busy: false,
  },
  onLoad() {
    if (wx.getStorageSync("token")) wx.reLaunch({ url: "/pages/feed/feed" });
  },
  input(e) {
    this.setData({ [e.currentTarget.dataset.key]: e.detail.value });
  },
  toggle() {
    this.setData({ register: !this.data.register });
  },
  demo() {
    this.setData({ username: "alice", password: "Alice123!" });
  },
  async submit() {
    if (this.data.busy) return;
    if (
      !/^[A-Za-z0-9_]{3,30}$/.test(this.data.username) ||
      this.data.password.length < 8
    ) {
      api.error(new Error("用户名须为 3–30 位，密码至少 8 位"));
      return;
    }
    this.setData({ busy: true });
    try {
      const { username, password, nickname } = this.data;
      if (this.data.register)
        await api.request("/auth/register", "POST", {
          username,
          password,
          nickname,
        });
      const result = await api.request("/auth/login", "POST", {
        username,
        password,
      });
      if(result.user.role==="admin"){throw Error("管理员请使用独立 Web 后台")}
      wx.setStorageSync("token", result.token);
      wx.setStorageSync("user", result.user);
      getApp().globalData.user = result.user;
      wx.reLaunch({ url: "/pages/feed/feed" });
    } catch (e) {
      api.error(e);
    } finally {
      this.setData({ busy: false });
    }
  },
});
