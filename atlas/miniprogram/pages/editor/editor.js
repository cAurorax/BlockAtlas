const api = require("../../utils/api");
Page({
 togglePack(){this.setData({attach:!this.data.attach,toggleLabel:!this.data.attach?"已选择附上当前草稿":"不附整包"})},
  data: {
    id: null,
    content: "",
    attach:false,toggleLabel:"不附整包",tags: "", mods:[{title:"不关联",slug:""}],selected:0,second:0,
    visibilityIndex: 0,
    visibilities: ["公开", "好友可见", "仅自己"],
    media: [],
    busy: false,
  },
  async onLoad(options) {
    try{this.setData({mods:[{title:"不关联",slug:""},...await api.request("/library")]})}catch(e){api.error(e)}
    if (options.id) {
      try {
        const p = await api.request("/posts/" + options.id);
        this.setData({
          id: p.id, selected:Math.max(0,this.data.mods.findIndex(x=>x.slug===p.mod_slug)),second:p.effect_second,
          content: p.content,
          tags: p.tags.join(","),
          visibilityIndex: ["public", "friends", "private"].indexOf(
            p.visibility,
          ),
          media: p.media.map((m) => ({ ...m, src: api.mediaUrl(m.url) })),
        });
        wx.setNavigationBarTitle({ title: "编辑动态" });
      } catch (e) {
        api.error(e);
      }
    }
  },
  input(e) {
    this.setData({ [e.currentTarget.dataset.key]: e.detail.value });
  },
  visibility(e) {
    this.setData({ visibilityIndex: Number(e.detail.value) });
  },
  choose() {
    if (this.data.busy) return;
    const count = 9 - this.data.media.length;
    if (count <= 0) {
      api.error(new Error("最多添加 9 个媒体"));
      return;
    }
    wx.chooseMedia({
      count,
      mediaType: ["image", "video"],
      sourceType: ["album", "camera"],
      maxDuration: 60,
      success: async (result) => {
        this.setData({ busy: true });
        wx.showLoading({ title: "正在上传" });
        try {
          for (const file of result.tempFiles) {
            if (file.size > 50 * 1024 * 1024)
              throw new Error("单个文件不能超过 50 MB");
            const m = await api.upload(file.tempFilePath);
            this.setData({
              media: this.data.media.concat({ ...m, src: api.mediaUrl(m.url) }),
            });
          }
        } catch (e) {
          api.error(e);
        } finally {
          wx.hideLoading();
          this.setData({ busy: false });
        }
      },
    });
  },
  remove(e) {
    if (this.data.busy) return;
    this.setData({
      media: this.data.media.filter((m) => m.id !== e.currentTarget.dataset.id),
    });
  },
  async submit() {
    if (this.data.busy) return;
    this.setData({ busy: true });
    try {
      const d = this.data;
      await api.request(
        "/posts" + (d.id ? "/" + d.id : ""),
        d.id ? "PUT" : "POST",
        {
          content: d.content,
          attach_pack:d.attach,mod_slug:d.mods[d.selected].slug,effect_second:Number(d.second||0),tags: d.tags
            .split(/[,，]/)
            .map((t) => t.trim())
            .filter(Boolean),
          visibility: ["public", "friends", "private"][d.visibilityIndex],
          media_ids: d.media.map((m) => m.id),
        },
      );
      wx.showToast({ title: "已保存" });
      wx.navigateBack();
    } catch (e) {
      api.error(e);
    } finally {
      this.setData({ busy: false });
    }
  },
});
