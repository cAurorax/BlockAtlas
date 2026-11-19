const api=require('../../utils/api');
Page({data:{pack:null,rows:[],text:'',busy:false,code:''},onShow(){this.load()},async load(){try{const [pack,mods]=await Promise.all([api.request('/pack'),api.request('/library')]);this.setData({pack,rows:pack.mods.map(k=>({...mods.find(m=>m.slug===k),locked:pack.locks.includes(k)}))})}catch(e){api.error(e)}},
 input(e){this.setData({text:e.detail.value})},async act(e){if(this.data.busy)return;const {op,k}=e.currentTarget.dataset;this.setData({busy:true});try{await api.request('/pack/action','POST',{op,value:op==='chat'?this.data.text:k||''});this.setData({code:'',text:''});await this.load()}catch(e){api.error(e)}finally{this.setData({busy:false})}},
 async exportPack(){try{const r=await api.request('/pack/export','POST');this.setData({code:r.code})}catch(e){api.error(e)}},copy(){wx.setClipboardData({data:this.data.code})},library(){wx.navigateTo({url:'/pages/library/library'})}
});
