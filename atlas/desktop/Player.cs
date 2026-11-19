using System;
using System.Drawing;
using System.IO;
using System.Diagnostics;
using System.Net;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;
class Player : Form {
 readonly bool smoke;
 readonly string proof=Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"..","evidence","desktop-smoke.txt");
 const string HomeUrl="http://127.0.0.1:18182/";
 readonly WebView2 web=new WebView2();
 readonly Label info=new Label { Text="正在连接方块工坊…",Dock=DockStyle.Fill,TextAlign=ContentAlignment.MiddleCenter };
 readonly string root=Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"..",".."));
 Player(bool test){smoke=test;if(smoke){ShowInTaskbar=false;Opacity=0;}Text="方块工坊 · Block Atlas";ClientSize=new Size(1320,860);MinimumSize=new Size(760,540);StartPosition=FormStartPosition.CenterScreen;Controls.Add(info);Shown+=async(s,e)=>await Boot();}
 async Task<bool> Ready(){try{using(var client=new WebClient()){var html=await client.DownloadStringTaskAsync(HomeUrl);return html.Contains("Block Atlas")||html.Contains("/static/app.js");}}catch{return false;}}
 Process Run(string file,string args){return Process.Start(new ProcessStartInfo(file,args){UseShellExecute=false,CreateNoWindow=true,WorkingDirectory=root});}
 async Task Boot(){try{
 if(!await Ready()){var py=Path.Combine(root,".venv","Scripts","python.exe");if(!File.Exists(py))throw new Exception("首次使用请运行 atlas\\start.cmd 安装依赖，再打开播放器。");
 using(var seed=Run(py,"-m atlas.seed")){await Task.Run(()=>seed.WaitForExit());if(seed.ExitCode!=0)throw new Exception("数据库初始化失败，请运行 start.cmd 查看原因。");}
 Run(py,"-m uvicorn atlas.server:app --host 127.0.0.1 --port 18182");for(int i=0;i<30&&!await Ready();i++)await Task.Delay(350);if(!await Ready())throw new Exception("本地服务未启动，请检查端口 18182。");}
 string profile=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"BlockAtlas","Player");
 var env=await CoreWebView2Environment.CreateAsync(null,profile,null);web.Dock=DockStyle.Fill;Controls.Add(web);web.BringToFront();await web.EnsureCoreWebView2Async(env);
 web.CoreWebView2.Settings.IsStatusBarEnabled=false;
 web.CoreWebView2.NewWindowRequested+=(s,e)=>{e.Handled=true;OpenExternal(e.Uri);};
 web.CoreWebView2.NavigationStarting+=(s,e)=>{if(!e.Uri.StartsWith(HomeUrl,StringComparison.OrdinalIgnoreCase)){e.Cancel=true;OpenExternal(e.Uri);}};
 if(smoke){web.CoreWebView2.NavigationCompleted+=async(s,e)=>{try{if(!e.IsSuccess)throw new Exception(e.WebErrorStatus.ToString());for(int n=0;n<50;n++){var found=await web.CoreWebView2.ExecuteScriptAsync("Boolean(document.querySelector('#username,.sidebar'))");if(found=="true"){File.WriteAllText(proof,"PASS: WinForms WebView2 created, page loaded, application UI rendered.");Environment.ExitCode=0;Close();return;}await Task.Delay(100);}throw new Exception("App did not render");}catch(Exception err){File.WriteAllText(proof,err.ToString());Environment.ExitCode=3;Close();}};}
 web.CoreWebView2.Navigate(HomeUrl);
 }catch(Exception ex){if(smoke){File.WriteAllText(proof,ex.ToString());Environment.ExitCode=3;Close();return;}web.Visible=false;info.Text="方块工坊未能启动\n\n"+ex.Message+"\n\n也可以打开本机服务的浏览器入口。";}}
 static void OpenExternal(string url){Uri u;if(Uri.TryCreate(url,UriKind.Absolute,out u)&&(u.Scheme=="https"||url.StartsWith(HomeUrl))) Process.Start(new ProcessStartInfo(u.AbsoluteUri){UseShellExecute=true});}
 [STAThread] static void Main(string[] args){Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);Application.Run(new Player(args.Length==1 && args[0]=="--smoke-test"));}
}
