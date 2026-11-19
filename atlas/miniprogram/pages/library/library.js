const api=require('../../utils/api');
Page({data:{items:[],shown:[],savedOnly:false,saved:[],q:'',link:'',found:null,busy:false},
 onShow(){this.load()},async load(){try{const [items,saved]=await Promise.all([api.request('/library'),api.request('/bookmarks')]);this.setData({items,saved});this.filter()}catch(e){api.error(e)}},
 filter(){const q=this.data.q.toLowerCase();this.setData({shown:this.data.items.filter(x=>!this.data.savedOnly||this.data.saved.includes(x.slug)).filter(x=>(x.title+x.slug+x.description).toLowerCase().includes(q))})},
 input(e){const k=e.currentTarget.dataset.key;this.setData({[k]:e.detail.value,...(k==='link'?{found:null}:{})});if(k==='q')this.filter()},
 async lookup(e){if(this.data.busy)return;this.setData({busy:true});const commit=e.currentTarget.dataset.op==='import';try{const found=await api.request('/library/'+(commit?'import':'preview'),'POST',{link:this.data.link});this.setData({found:commit?null:found});if(commit){wx.showToast({title:'已导入'});await this.load()}}catch(e){api.error(e)}finally{this.setData({busy:false})}},
 only(){this.setData({savedOnly:!this.data.savedOnly});this.filter()},
 async notes(e){try{const k=e.currentTarget.dataset.slug;const [a,rows]=await Promise.all([api.request('/library/'+k+'/notes'),api.request('/bookmarks')]);this.setData({active:k,version:this.data.items.find(x=>x.slug===k).version,n:a,saved:rows,note:'',outcome:0,outcomes:['成功','异常','未启动']})}catch(e){api.error(e)}},
 async star(){try{await api.request('/library/'+this.data.active+'/bookmark','PUT');await this.notes({currentTarget:{dataset:{slug:this.data.active}}});this.filter()}catch(e){api.error(e)}},
 async submitNote(){try{await api.request('/library/'+this.data.active+'/notes','POST',{version:this.data.version,note:this.data.note,result:this.data.outcomes[this.data.outcome]});await this.notes({currentTarget:{dataset:{slug:this.data.active}}})}catch(e){api.error(e)}},
 async add(e){try{await api.request('/pack/action','POST',{op:'add',value:e.currentTarget.dataset.slug});this.bench()}catch(e){api.error(e)}},bench(){wx.navigateTo({url:'/pages/bench/bench'})}
});
