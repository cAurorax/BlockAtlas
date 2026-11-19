const api = require("../../utils/api");
Page({
  stream(){wx.navigateTo({url:'/pages/feed/feed?scope=friends'})},
  data: { friends: [], results: [], q: "", uid: 0 },
  onShow() {
    this.setData({ uid: getApp().globalData.user?.id });
    this.load();
  },
  async load() {
    try {
      this.setData({ friends: await api.request("/friends") });
    } catch (e) {
      api.error(e);
    }
  },
  input(e) {
    this.setData({ q: e.detail.value });
  },
  async search() {
    try {
      this.setData({
        results: await api.request(
          "/users/search?q=" + encodeURIComponent(this.data.q),
        ),
      });
    } catch (e) {
      api.error(e);
    }
  },
  async add(e) {
    try {
      await api.request("/friends", "POST", {
        user_id: e.currentTarget.dataset.id,
      });
      wx.showToast({ title: "申请已发送" });
      await this.load();
    } catch (err) {
      api.error(err);
    }
  },
  async accept(e) {
    try {
      await api.request("/friends/" + e.currentTarget.dataset.id, "PUT", {
        action: "accept",
      });
      await this.load();
    } catch (err) {
      api.error(err);
    }
  },
  async remove(e) {
    if (!(await api.confirm("移除此好友关系或申请？"))) return;
    try {
      await api.request("/friends/" + e.currentTarget.dataset.id, "DELETE");
      await this.load();
    } catch (err) {
      api.error(err);
    }
  },
});
