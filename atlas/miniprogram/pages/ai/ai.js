const api = require("../../utils/api");

const CHANNELS = [
  { kind: "text", title: "对话改包", label: "文本模型", local: "本地指令", page: "/pages/bench/bench", providers: ["DeepSeek", "阿里云百炼（北京）", "OpenAI", "自填支持的兼容地址"] },
  { kind: "vision", title: "截图找玩法", label: "视觉模型", local: "本地图库", page: "/pages/vision/vision", providers: ["阿里云百炼（北京）", "OpenAI", "自填支持的兼容地址"] },
];
const URLS = {
  DeepSeek: "https://api.deepseek.com/chat/completions",
  "阿里云百炼（北京）": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
  OpenAI: "https://api.openai.com/v1/chat/completions",
};
function channel(kind) { return CHANNELS.find((item) => item.kind === kind); }
function draft(kind, cfg) {
  const c = channel(kind), personal = cfg.has_personal;
  const url = (personal && cfg.url) || URLS[c.providers[0]];
  const index = c.providers.findIndex((name) => URLS[name] === url);
  return { kind, url, model: personal ? cfg.model : "", key: "", enabled: personal ? cfg.enabled : true,
    hasKey: personal && cfg.has_key, originalUrl: personal ? cfg.url : "",
    providers: c.providers, index: index < 0 ? c.providers.length - 1 : index };
}

Page({
  data: { loading: true, busy: false, error: "", cards: [], form: null, notice: "", invalid: false },
  onShow() { this.refresh(); },
  onHide() { this.setData({ form: null, notice: "" }); },
  onPullDownRefresh() {
    if (this.data.form || this.data.busy) return wx.stopPullDownRefresh();
    this.refresh().finally(() => wx.stopPullDownRefresh());
  },
  async refresh() {
    this.setData({ loading: true, error: "" });
    try {
      const cfg = await api.request("/me/ai");
      this.setData({ cards: CHANNELS.map((c) => ({
        ...c, ...cfg[c.kind], mode: cfg[c.kind].enabled ? cfg[c.kind].model : c.local,
      })) });
      return true;
    } catch (e) {
      this.setData({ error: e.message || "无法读取个人模型设置" }); return false;
    } finally { this.setData({ loading: false }); }
  },
  say(text, invalid = false) { this.setData({ notice: text, invalid }); },
  async edit(e) {
    if (this.data.busy) return;
    const kind = e.currentTarget.dataset.kind;
    if (this.data.form && !(await api.confirm("放弃当前未保存的输入？"))) return;
    this.setData({ form: draft(kind, this.data.cards.find((x) => x.kind === kind)), notice: "" });
  },
  cancel() { this.setData({ form: null, notice: "" }); },
  change(e) {
    const field = e.currentTarget.dataset.field;
    if (this.data.busy || !["url","model","key"].includes(field)) return;
    const updates = { ["form."+field]: e.detail.value, notice: "" };
    if (field === "url") {
      const f = this.data.form;
      const i = f.providers.findIndex((v) => URLS[v] === e.detail.value.trim());
      updates["form.index"] = i < 0 ? f.providers.length-1 : i;
    }
    this.setData(updates);
  },
  provider(e) {
    const index = Number(e.detail.value), name = this.data.form.providers[index];
    this.setData({ "form.index": index, "form.url": URLS[name] || "", "form.key":"", notice: "" });
  },
  toggle() { this.setData({ "form.enabled": !this.data.form.enabled, notice: "" }); },
  async save() {
    const f = this.data.form;
    if (!f || this.data.busy) return;
    const body = { enabled:f.enabled, url:f.url.trim(), model:f.model.trim(), key:f.key.trim() };
    const retaining = f.hasKey && body.url === f.originalUrl;
    if (body.enabled && (!body.url || !body.model || (!body.key && !retaining)))
      return this.say("启用模型需填写地址、模型 ID 和个人密钥。", true);
    if (f.hasKey && body.url !== f.originalUrl && !body.key)
      return this.say("切换服务地址需重新输入对应的个人密钥。", true);
    this.setData({busy:true});
    try {
      await api.request("/me/ai/"+f.kind,"POST",body);
      this.setData({ form:null });
      await this.refresh(); this.say(body.enabled ? "个人模型设置已保存。可测试连接。" : "已为本账号停用此通道。");
    } catch(e) { this.say(e.message, true); }
    finally { this.setData({busy:false}); }
  },
  async test(e) {
    if (this.data.busy) return;
    const kind = e.currentTarget.dataset.kind;
    this.setData({busy:true});
    try {
      if (!(await api.confirm("将使用你已保存的个人密钥发送一次测试请求，服务商可能计费。继续吗？"))) return;
      const r = await api.request("/me/ai/"+kind+"/test","POST");
      this.say(r.message || "连接测试通过");
    } catch(e) { this.say(e.message,true); }
    finally { this.setData({busy:false}); }
  },
  async restore(e) {
    if (this.data.busy) return;
    const kind = e.currentTarget.dataset.kind;
    this.setData({busy:true});
    try {
      if (!(await api.confirm("移除此通道的个人设置和密钥，恢复使用社区默认配置？此操作不影响其他玩家。"))) return;
      await api.request("/me/ai/"+kind,"DELETE");
      this.setData({form:null});
      await this.refresh(); this.say("已恢复使用社区默认设置。");
    } catch(e) { this.say(e.message,true); }
    finally { this.setData({busy:false}); }
  },
  open(e) { wx.navigateTo({url:channel(e.currentTarget.dataset.kind).page}); },
});
