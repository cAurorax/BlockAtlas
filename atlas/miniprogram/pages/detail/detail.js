const api = require("../../utils/api");
Page({
  authorHome(e){wx.navigateTo({url:'/pages/player/player?uid='+e.currentTarget.dataset.uid})},
 release(){wx.navigateTo({url:"/pages/release/release?pid="+this.data.id+"&vid="+this.data.post.pack.id})},
 report(){wx.showModal({title:"举报帖子",editable:true,placeholderText:"请说明问题",success:async r=>{if(!r.confirm)return;try{await api.request("/posts/"+this.data.id+"/report","POST",{reason:r.content});wx.showToast({title:"已提交"})}catch(e){api.error(e)}}})},
 seek(){const v=this.data.post.media.find(x=>x.kind==="video");if(v){const ctx=wx.createVideoContext("clip-"+v.id,this);ctx.seek(this.data.post.effect_second);ctx.play()}else wx.navigateTo({url:"/pages/library/library"})},
 async collect(){try{await api.request("/pack/action","POST",{op:"add",value:this.data.post.mod_slug});wx.navigateTo({url:"/pages/bench/bench"})}catch(e){api.error(e)}},
  data: {
    id: 0,
    post: null,
    comments: [],
    user: null,
    content: "",
    reply: null,
    replyName: "",
    scores: ["1 星", "2 星", "3 星", "4 星", "5 星"],
    busy: false,
  },
  onLoad(options) {
    this.setData({ id: Number(options.id), user: getApp().globalData.user });
  },
  onShow() {
    this.load();
  },
  async load() {
    try {
      const [p, c] = await Promise.all([
        api.request("/posts/" + this.data.id),
        api.request("/posts/" + this.data.id + "/comments"),
      ]);
      this.setData({
        post: api.decorate(p),
        comments: c.map((x) => ({
          ...x,
          replyName: c.find((y) => y.id === x.parent_id)?.nickname || "",
        })),
      });
    } catch (e) {
      api.error(e);
    }
  },
  input(e) {
    this.setData({ content: e.detail.value });
  },
  reply(e) {
    this.setData({
      reply: e.currentTarget.dataset.id,
      replyName: e.currentTarget.dataset.name,
    });
  },
  cancelReply() {
    this.setData({ reply: null, replyName: "" });
  },
  async comment() {
    if (this.data.busy) return;
    this.setData({ busy: true });
    try {
      await api.request("/posts/" + this.data.id + "/comments", "POST", {
        content: this.data.content,
        parent_id: this.data.reply,
      });
      this.setData({ content: "", reply: null, replyName: "" });
      await this.load();
    } catch (e) {
      api.error(e);
    } finally {
      this.setData({ busy: false });
    }
  },
  async rate(e) {
    try {
      await api.request("/posts/" + this.data.id + "/rating", "PUT", {
        score: Number(e.detail.value) + 1,
      });
      await this.load();
      wx.showToast({ title: "评分已保存" });
    } catch (e) {
      api.error(e);
    }
  },
  edit() {
    wx.navigateTo({ url: "/pages/editor/editor?id=" + this.data.id });
  },
  async remove() {
    if (!(await api.confirm("删除动态及其评论、评分和媒体？此操作不可恢复。")))
      return;
    try {
      await api.request("/posts/" + this.data.id, "DELETE");
      wx.navigateBack();
    } catch (e) {
      api.error(e);
    }
  },
  async removeComment(e) {
    if (!(await api.confirm("删除此评论及其回复？"))) return;
    try {
      await api.request("/comments/" + e.currentTarget.dataset.id, "DELETE");
      await this.load();
    } catch (err) {
      api.error(err);
    }
  },
  preview(e) {
    wx.previewImage({ urls: [e.currentTarget.dataset.src] });
  },
});
