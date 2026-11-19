const api=require('../../utils/api');
const labels={self:'这是你自己',none:'＋ 申请好友',incoming:'接受好友申请',outgoing:'已申请 · 等待确认',accepted:'已是好友'};
Page({
  data:{player:null,posts:[],page:0,total:0,busy:false,acting:false,error:''},
  onLoad(o){this.uid=Number(o.uid)},
  onShow(){this.load(true)},onReachBottom(){if(this.data.posts.length<this.data.total&&!this.data.busy)this.load(false)},
  async load(reset){const page=reset?1:this.data.page+1;const seq=this.seq=(this.seq||0)+1;
    this.setData({busy:true,error:''});
    try{const [p,r]=await Promise.all([api.request('/players/'+this.uid),api.request('/posts?author_id='+this.uid+'&page='+page)]);
      if(this.seq!==seq)return;
      this.setData({player:p,label:labels[p.relationship],canAct:['none','incoming'].includes(p.relationship),portrait:p.id%3,page,total:r.total,posts:(reset?[]:this.data.posts).concat(r.items.map(x=>({...api.decorate(x),title:x.content.split('\n')[0]||'媒体动态'})))});
    }catch(e){if(this.seq===seq)this.setData({error:e.message})}finally{if(this.seq===seq)this.setData({busy:false})}},
  retry(){this.load(true)},
  async act(){if(this.data.acting||!this.data.canAct)return;this.setData({acting:true});
    try{const p=this.data.player,incoming=p.relationship==='incoming';await api.request(incoming?'/friends/'+p.friend_id:'/friends',incoming?'PUT':'POST',incoming?{action:'accept'}:{user_id:p.id});wx.showToast({title:incoming?'已成为好友':'已发送好友申请'})}catch(e){api.error(e)}finally{await this.load(true);this.setData({acting:false})}},
  detail(e){wx.navigateTo({url:'/pages/detail/detail?id='+e.currentTarget.dataset.id})}
});
