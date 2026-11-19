const api = require("../../utils/api");
Page({
  authorHome(e){wx.navigateTo({url:'/pages/player/player?uid='+e.currentTarget.dataset.uid})},
  aiWorkshop() {
    wx.navigateTo({ url: "/pages/ai/ai" });
  },
 lens(){wx.navigateTo({url:"/pages/vision/vision"})},
 library(){wx.navigateTo({url:"/pages/library/library"})},bench(){wx.navigateTo({url:"/pages/bench/bench"})},
  data: { banner:getApp().globalData.baseUrl+"/static/images/iris-scene.jpg",
    filterOpen: false, hasFilter: false, applied: {},
    posts: [],
    scope: "all",
    q: "",
    tag: "",
    start: "",
    end: "",
    page: 1,
    total: 0,
    busy: false,
  },
  onLoad(o){const scope=['mine','friends'].includes(o.scope)?o.scope:'all';this.setData({scope,portrait:Math.abs(Number(getApp().globalData.user?.id)||0)%3,initial:(getApp().globalData.user?.nickname||'我').slice(0,1)});wx.setNavigationBarTitle({title:{all:'玩家广场',mine:'我的发布',friends:'好友动态'}[scope]})},
  onShow() {
    this.load(true);
  },
  onPullDownRefresh() {
    this.load(true).finally(() => wx.stopPullDownRefresh());
  },
  onReachBottom() {
    if (this.data.posts.length < this.data.total && !this.data.busy)
      this.load(false);
  },
  async load(reset) {
    if (!reset && this.data.busy) return;
    const stamp = (this.requestStamp || 0) + 1;
    this.requestStamp = stamp;
    this.setData({ busy: true });
    try {
      const page = reset ? 1 : this.data.page + 1;
      const args = { scope: this.data.scope, ...this.data.applied };
      const query = Object.keys(args).filter(k => args[k])
        .map(k => k + "=" + encodeURIComponent(args[k])).join("&");
      const r = await api.request("/posts?" + query + "&page=" + page);
      if (this.requestStamp !== stamp) return;
      this.setData({
        posts: reset
          ? r.items.map(api.decorate)
          : this.data.posts.concat(r.items.map(api.decorate)),
        total: r.total,
        page,
      });
    } catch (e) {
      if (this.requestStamp === stamp) api.error(e);
    } finally {
      if (this.requestStamp === stamp) this.setData({ busy: false });
    }
  },
  input(e) {
    this.setData({ [e.currentTarget.dataset.key]: e.detail.value });
  },
  toggleFilter() {
    const {q = "", tag = "", start = "", end = ""} = this.data.applied;
    this.setData({filterOpen: !this.data.filterOpen, q, tag, start, end});
  },
  search() {
    const {q, tag, start, end} = this.data;
    if (start && end && start > end) return api.error(new Error("开始日期不能晚于结束日期"));
    const applied = {q: q.trim(), tag: tag.trim(), start, end};
    this.setData({applied, hasFilter: Object.values(applied).some(Boolean), filterOpen:false});
    this.load(true);
  },
  reset() {
    this.setData({ q: "", tag: "", start: "", end: "", applied: {}, hasFilter: false, filterOpen: false });
    this.load(true);
  },
  detail(e) {
    wx.navigateTo({
      url: "/pages/detail/detail?id=" + e.currentTarget.dataset.id,
    });
  },
  publish() {
    wx.navigateTo({ url: "/pages/editor/editor" });
  },
  friends() {
    wx.navigateTo({ url: "/pages/friends/friends" });
  },
  profile(){this.setData({accountOpen:!this.data.accountOpen})},
  onHide(){this.setData({accountOpen:false})},
  myPosts(){this.setData({accountOpen:false});wx.navigateTo({url:'/pages/feed/feed?scope=mine'})},
  myAccount(){this.setData({accountOpen:false});wx.navigateTo({url:'/pages/profile/profile'})},
  async signOut(){this.setData({accountOpen:false});try{await api.request('/auth/logout','POST');wx.removeStorageSync('token');wx.removeStorageSync('user');getApp().globalData.user=null;wx.reLaunch({url:'/pages/login/login'})}catch(e){api.error(e)}},
  preview(e) {
    wx.previewImage({ urls: [e.currentTarget.dataset.src] });
  },
});
