// 启动游戏：固定 Minecraft 1.20.1 / Fabric 0.19.4，只暴露启动期可调项
// （内存、窗口大小、窗口标题、Java），设置按用户存库，启动后轮询进程状态。
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );

const megabyte = (value) => `${Math.round(Number(value || 0) / 1024)} GB`;

export async function launchView({ api, toast }) {
  const root = document.querySelector("#content");
  if (!root) return;

  let boot = null; // /launch/settings payload
  let status = null; // /launch/status payload
  let draft = null; // unsaved form state
  let timer = null;
  let installTimer = null;
  let epoch = 0;
  let showLog = false;
  let logOffset = -1; // byte cursor so the log appends instead of re-rendering
  let logLines = 0;
  let logBusy = false;
  const LOG_LINE_CAP = 2000;

  // ---- helpers -----------------------------------------------------------

  const state = () => boot?.state || {};
  const settings = () => draft || boot?.settings || {};
  const installBadge = () => {
    const map = {
      ready: ["ok", "可启动"],
      not_installed: ["bad", "未安装"],
      loader_missing: ["warn", "缺加载器"],
    };
    const [tone, text] = map[state().state] || ["warn", "未知"];
    return `<span class="launch-badge ${tone}">${esc(text)}</span>`;
  };

  async function load() {
    const mine = ++epoch;
    const data = await api("/launch/settings");
    if (mine !== epoch || !root.isConnected) return;
    boot = data;
    if (!draft) draft = { ...data.settings };
    if (!draft.java_path) draft.java_path = preferJava(data.java);
    paint();
    await refreshStatus();
    scheduleInstallPoll();
  }

  function preferJava(list) {
    const rows = list || [];
    // Prefer the Mojang runtime bundled with this version, then a modern JDK;
    // the version is a preference only, never a hard requirement.
    return (
      (rows.find((row) => row.source === "mojang" && row.major >= 17 && row.major <= 21) ||
        rows.find((row) => row.major >= 17 && row.major <= 21) ||
        rows.find((row) => row.major >= 17) ||
        rows[0] ||
        {}
      ).path || ""
    );
  }

  async function refreshStatus() {
    try {
      status = await api("/launch/status");
    } catch {
      status = null;
    }
    paintStatus();
    paintInstall();
    if (status?.state && boot) boot.state = status.state;
    schedule();
  }

  function schedule() {
    clearTimeout(timer);
    const running = Boolean(status?.running);
    const installing = status?.install?.status === "running";
    if (running || installing) timer = setTimeout(refreshStatus, running ? 2000 : 1200);
  }

  /// Poll the install endpoint while an install runs. ``force`` covers the
  /// moment right after POST, when the worker may not have reported yet.
  function scheduleInstallPoll(force = false) {
    clearTimeout(installTimer);
    const running = status?.install?.status === "running";
    if (!running && !force) return;
    installTimer = setTimeout(async () => {
      try {
        const data = await api("/launch/install");
        status = status || {};
        status.install = data.task;
        status.state = data.state;
        if (boot) boot.state = data.state;
      } catch {
        return;
      }
      paintInstall();
      paintStatus();
      if (status.install.status === "running") scheduleInstallPoll();
      else if (status.install.status === "success") {
        toast("游戏本体安装完成");
        refreshStatus();
      }
    }, force ? 400 : 1200);
  }

  // ---- paint -------------------------------------------------------------

  function paint() {
    const data = settings();
    const version = boot?.pinned || {};
    const limits = boot?.limits || {};
    const recommendation = boot?.recommendation || {};
    root.innerHTML = `<div class="page-head"><div><h1>启动游戏</h1><p>版本固定为 Minecraft ${esc(version.minecraft)} · ${esc(version.loader)} ${esc(version.loader_version)}。这里只调整启动方式，不改游戏内容。</p></div></div>
      <div class="launch-layout">
        <section class="launch-card">
          <h2>启动配置 ${installBadge()}</h2>
          <p class="launch-sub">设置会按账号保存，下次进入自动带回。</p>
          <div class="launch-pin"><span>MINECRAFT ${esc(version.minecraft)}</span><span>${esc((version.loader || "").toUpperCase())} ${esc(version.loader_version)}</span><span>${esc(boot?.mods?.planning_count ?? 0)} 个 Mod</span></div>
          <div id="lv-install-slot">${installMarkup()}</div>
          ${memoryMarkup(data, recommendation, limits)}
          ${windowMarkup(data, limits)}
          ${javaMarkup(data, boot?.java || [])}
          <div class="launch-section">
            <h3>离线身份</h3>
            <div class="launch-row">
              <div class="launch-field"><label for="lv-username">游戏内用户名</label><input id="lv-username" maxlength="16" value="${esc(data.username)}" placeholder="1-16 位字母、数字或下划线"></div>
            </div>
            <p class="hint">离线模式启动，仅本机回环地址可用；用户名决定本地存档与皮肤标识。</p>
          </div>
        </section>
        <aside class="launch-card launch-status" id="lv-status"></aside>
      </div>
      <div class="launch-dock">
        <span class="launch-dock-note" id="lv-dock-note"></span>
        <button type="button" class="ghost" id="lv-save">保存配置</button>
        <button type="button" id="lv-toggle">启动游戏</button>
      </div>`;
    bindInstall();
    bind();
    paintStatus();
  }

  /// 本体未就绪时给出「安装游戏本体」，让新机器也能把功能跑通。
  function installMarkup() {
    const task = status?.install || boot?.install || {};
    const running = task.status === "running";
    const st = state();
    if (st.state === "ready") {
      return `<div class="launch-section launch-install"><h3>游戏本体</h3>
        <p class="launch-install-ok">已就绪 · ${esc(st.launch_version || "")}</p>
        <button type="button" class="small ghost" id="lv-reinstall">重新安装</button>
        <p class="hint">安装目录：<code>${esc(st.minecraft_dir || "")}</code></p>
        <div id="lv-install-progress" hidden></div>
      </div>`;
    }
    const percent = Number(task.percent || 0);
    return `<div class="launch-section launch-install"><h3>游戏本体</h3>
      <div class="launch-callout"><b>${esc(st.detail || "游戏本体未就绪")}</b>。安装会下载 Minecraft ${esc(st.minecraft || "")}、${esc(st.loader || "")} ${esc(st.loader_version || "")} 与 Mojang Java 运行时，约 500 MB。</div>
      <div class="launch-presets"><button type="button" class="small" id="lv-install" ${running ? "disabled" : ""}>${running ? "安装中…" : "安装游戏本体"}</button></div>
      <p class="hint">安装目录：<code>${esc(st.minecraft_dir || "")}</code></p>
      <div id="lv-install-progress" ${running ? "" : "hidden"}>
        <div class="launch-install-bar"><i id="lv-install-fill" class="${running ? "is-running" : ""}" style="width:${running ? "" : percent + "%"}"></i></div>
        <p class="launch-install-line"><span id="lv-install-stage"></span><span id="lv-install-percent"></span></p>
        <p class="launch-install-detail" id="lv-install-detail"></p>
      </div>
    </div>`;
  }

  /// Patch the install panel in place. The node skeleton stays put so the
  /// progress animation runs smoothly instead of restarting on every poll.
  function paintInstall() {
    const task = status?.install;
    const slot = root.querySelector("#lv-install-slot");
    if (!task || !slot) return;
    const wantReady = state().state === "ready";
    // Only rebuild when the panel's overall shape changes, not on progress.
    const shape = `${wantReady ? "ready" : "missing"}|${task.status === "running" ? "run" : "idle"}`;
    if (slot.dataset.shape !== shape) {
      slot.dataset.shape = shape;
      slot.innerHTML = installMarkup();
      bindInstall();
    }
    const wrap = root.querySelector("#lv-install-progress");
    const fill = root.querySelector("#lv-install-fill");
    const stage = root.querySelector("#lv-install-stage");
    const percent = root.querySelector("#lv-install-percent");
    const detail = root.querySelector("#lv-install-detail");
    if (wrap) wrap.hidden = task.status !== "running" && task.status !== "failed";
    if (fill) {
      const running = task.status === "running";
      fill.classList.toggle("is-running", running);
      if (!running) fill.style.width = task.status === "success" ? "100%" : "0%";
    }
    if (stage)
      stage.textContent =
        task.status === "failed" ? "安装失败" : task.stage || "";
    if (percent)
      percent.textContent =
        task.status === "running"
          ? `阶段 ${Math.min(Number(task.current || 0) + 1, Number(task.total || 2))}/${task.total || 2}`
          : task.status === "success"
            ? "完成"
            : task.status === "failed"
              ? "失败"
              : "";
    if (detail)
      detail.textContent =
        task.status === "failed" ? task.error || "" : task.detail || "";
    const button = root.querySelector("#lv-install");
    if (button) {
      const running = task.status === "running";
      button.disabled = running;
      const label = running ? "安装中…" : "安装游戏本体";
      if (button.textContent !== label) button.textContent = label;
    }
  }

  function bindInstall() {
    const install = root.querySelector("#lv-install");
    if (install)
      install.onclick = async () => {
        install.disabled = true;
        install.textContent = "安装中…";
        try {
          const data = await api("/launch/install", { method: "POST" });
          status = status || {};
          status.install = data.task;
          status.state = data.state;
          paintInstall();
          scheduleInstallPoll();
        } catch (error) {
          toast(error.message);
          install.disabled = false;
          install.textContent = "安装游戏本体";
        }
      };
    const reinstall = root.querySelector("#lv-reinstall");
    if (reinstall)
      reinstall.onclick = async () => {
        reinstall.disabled = true;
        try {
          const data = await api("/launch/install", { method: "POST" });
          status = status || {};
          status.install = data.task;
          status.state = data.state;
          paintInstall();
          scheduleInstallPoll();
        } catch (error) {
          toast(error.message);
          reinstall.disabled = false;
        }
      };
  }
  function memoryMarkup(data, recommendation, limits) {
    const auto = data.memory_mode === "auto";
    return `<div class="launch-section">
      <h3>内存分配</h3>
      <div class="launch-toggle" role="group" aria-label="内存分配模式">
        <button type="button" data-memory-mode="auto" class="${auto ? "active" : ""}">自动</button>
        <button type="button" data-memory-mode="manual" class="${auto ? "" : "active"}">手动</button>
      </div>
      <div id="lv-memory-body"></div>
      <p class="hint">调整的是 JVM 最大堆（-Xmx）。内存越大不等于越流畅，超过实际可用会反而拖慢。</p>
    </div>`;
  }

  function memoryBodyMarkup(data, recommendation, limits) {
    const auto = data.memory_mode === "auto";
    const min = limits.memory_min || 1024;
    const max = limits.memory_max || 32768;
    if (auto) {
      const reasons = (recommendation.reasons || [])
        .map((line) => `<li>${esc(line)}</li>`)
        .join("");
      return `<div class="launch-auto"><div><small>根据 ${esc(recommendation.mod_count ?? 0)} 个 Mod 与本机内存推荐</small><b>${esc(recommendation.suggested_mb)} MB</b><ul>${reasons}</ul></div><button type="button" class="small ghost" data-memory-adopt>改用手动</button></div>`;
    }
    return `<div class="launch-memory">
        <input id="lv-memory-range" type="range" min="${min}" max="${max}" step="256" value="${esc(data.memory_mb)}" aria-label="内存大小">
        <input id="lv-memory-number" type="number" min="${min}" max="${max}" step="256" value="${esc(data.memory_mb)}" aria-label="内存 MB">
        <span class="launch-memory-unit">MB</span>
      </div>
      <div class="launch-presets">${[2048, 4096, 6144, 8192]
        .map((value) => `<button type="button" data-memory-preset="${value}">${value}</button>`)
        .join("")}<button type="button" data-memory-adopt>用推荐值 ${esc(recommendation.suggested_mb ?? 4096)}</button></div>`;
  }

  function windowMarkup(data, limits) {
    return `<div class="launch-section">
      <h3>启动窗口</h3>
      <div class="launch-row">
        <div class="launch-field"><label for="lv-width">窗口宽度</label><input id="lv-width" type="number" min="${limits.width_min || 640}" max="${limits.size_max || 7680}" step="1" value="${esc(data.width)}"></div>
        <div class="launch-field"><label for="lv-height">窗口高度</label><input id="lv-height" type="number" min="${limits.height_min || 480}" max="${limits.size_max || 7680}" step="1" value="${esc(data.height)}"></div>
      </div>
      <div class="launch-presets">${[
        [1280, 720],
        [1600, 900],
        [1920, 1080],
        [2560, 1440],
      ]
        .map(
          ([w, h]) =>
            `<button type="button" data-size-preset="${w}x${h}">${w} × ${h}</button>`,
        )
        .join("")}</div>
      <p class="hint">宽度和高度会作为游戏的初始窗口尺寸；进入游戏后仍可按 F11 切换全屏。</p>
    </div>`;
  }

  function javaMarkup(data, list) {
    const rows = list.length
      ? list
          .map((item) => {
            const active = item.path === data.java_path;
            // Version is shown for reference only. Gating Java by version
            // would need per-Minecraft-version rules, so the picker stays open.
            const tone = item.major
              ? `<span class="ok">Java ${esc(item.major)}</span>`
              : `<span class="ok">未探测</span>`;
            return `<label class="launch-java-item ${active ? "active" : ""}">
              <input type="radio" name="lv-java" value="${esc(item.path)}" ${active ? "checked" : ""}>
              <span class="meta"><b>${esc(item.version || "未知版本")} · ${esc(item.vendor || "未知发行方")}</b><small>${esc(item.path)}</small><small>${esc(item.arch || "")} ${item.source === "mojang" ? "· Mojang 运行时" : ""}</small></span>
              ${tone}
            </label>`;
          })
          .join("")
      : `<div class="launch-java-empty">还没有扫描过本机 Java，点上方「扫描本机 Java」。</div>`;
    return `<div class="launch-section">
      <h3>Java 运行环境</h3>
      <div class="launch-java">
        <div class="launch-presets"><button type="button" class="small" id="lv-java-scan">扫描本机 Java</button><button type="button" class="small ghost" id="lv-java-manual">手动填写路径</button></div>
        <div class="launch-java-list" id="lv-java-list">${rows}</div>
      </div>
      <p class="hint">启动游戏会使用选中的 Java。扫描会读取常见安装目录与 Mojang 自带运行时，结果存库供以后直接选择。</p>
    </div>`;
  }

  function paintStatus() {
    const host = root.querySelector("#lv-status");
    if (!host) return;
    // Build the skeleton once, then only patch text nodes. Rebuilding the
    // whole panel every poll made the log area flash on every refresh.
    if (!host.dataset.built) {
      host.innerHTML = `<h2 style="font-size:14px;margin:0 0 10px">运行状态</h2>
        <div class="kv"><span>版本</span><b id="lv-sv-version"></b></div>
        <div class="kv"><span>本体</span><b id="lv-sv-state"></b></div>
        <div class="kv"><span>Java</span><b id="lv-sv-java"></b></div>
        <div class="kv"><span>进程</span><b id="lv-sv-process"></b></div>
        <div class="kv" id="lv-sv-args-row" hidden><span>启动参数</span><b id="lv-sv-args"></b></div>
        <div class="launch-actions">
          <button type="button" class="small ghost" id="lv-log-toggle"></button>
          <button type="button" class="small ghost" id="lv-refresh">刷新</button>
        </div>
        <div class="launch-log" id="lv-log-wrap" hidden><pre id="lv-log-text"></pre></div>`;
      host.dataset.built = "1";
      // A fresh panel has an empty <pre>, so the next log read must start over.
      logOffset = -1;
      logLines = 0;
      host.querySelector("#lv-refresh").onclick = () => refreshStatus();
      host.querySelector("#lv-log-toggle").onclick = () => toggleLog();
    }
    const game = status?.game;
    const running = Boolean(status?.running);
    const st = status?.state || state();
    setText(host, "#lv-sv-version", `${st.minecraft} / ${st.loader} ${st.loader_version}`);
    setText(host, "#lv-sv-state", st.detail || "");
    setText(host, "#lv-sv-java", settings().java_path || "未选择");
    const processText = running
      ? "运行中"
      : game
        ? `已退出（退出码 ${game.exit_code}）`
        : "未启动";
    const processNode = host.querySelector("#lv-sv-process");
    if (processNode) {
      // Compare before writing: an unchanged innerHTML still triggers a repaint.
      const next = running
        ? `<span class="launch-badge run">运行中 PID ${esc(game.pid)}</span>`
        : esc(processText);
      if (processNode.innerHTML !== next) processNode.innerHTML = next;
    }
    const argsRow = host.querySelector("#lv-sv-args-row");
    if (argsRow) {
      argsRow.hidden = !game;
      if (game)
        setText(
          host,
          "#lv-sv-args",
          `${game.settings?.memory_mb} MB · ${game.settings?.width}×${game.settings?.height}`,
        );
    }
    const logButton = host.querySelector("#lv-log-toggle");
    if (logButton) {
      const label = showLog ? "隐藏日志" : "查看日志";
      if (logButton.textContent !== label) logButton.textContent = label;
      logButton.className = "small" + (showLog ? "" : " ghost");
    }
    const wrap = host.querySelector("#lv-log-wrap");
    if (wrap) wrap.hidden = !showLog;
    syncToggle();
    if (showLog) paintLog();
  }

  function setText(host, selector, value) {
    const node = host.querySelector(selector);
    if (node && node.textContent !== String(value)) node.textContent = String(value);
  }

  function toggleLog() {
    showLog = !showLog;
    if (!showLog) logOffset = -1;
    paintStatus();
    if (showLog) paintLog();
  }

  /// The dock button doubles as start and stop, so it always reflects the
  /// process state: running → 危险色「停止游戏」, otherwise 主色「启动游戏」.
  function syncToggle() {
    const button = root.querySelector("#lv-toggle");
    const note = root.querySelector("#lv-dock-note");
    if (!button) return;
    const running = Boolean(status?.running);
    const game = status?.game;
    if (running) {
      button.textContent = "停止游戏";
      button.className = "danger";
      button.disabled = false;
      if (note)
        note.textContent = `PID ${game.pid} · ${game.settings?.memory_mb ?? ""} MB · ${game.settings?.width ?? ""}×${game.settings?.height ?? ""}`;
      return;
    }
    button.textContent = "启动游戏";
    button.className = "";
    button.disabled = !state().launchable;
    if (note)
      note.textContent = state().launchable
        ? "启动前会自动保存当前配置"
        : state().detail || "游戏本体未就绪";
  }

  /// Append only what is new. A full re-read of the tail every poll made the
  /// panel flash, so the server hands back a byte offset we feed forward.
  async function paintLog() {
    const pre = root.querySelector("#lv-log-text");
    if (!pre || logBusy) return;
    logBusy = true;
    try {
      const query = logOffset < 0 ? "?lines=160" : `?offset=${logOffset}`;
      const data = await api("/launch/logs" + query);
      logOffset = Number(data.offset ?? 0);
      if (data.reset) {
        pre.textContent = data.text || "（还没有日志）";
        logLines = pre.textContent.split("\n").length;
        pre.scrollTop = pre.scrollHeight;
        return;
      }
      if (!data.text) return;
      const nearBottom = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 40;
      pre.append(document.createTextNode(data.text));
      logLines += data.text.split("\n").length - 1;
      if (logLines > LOG_LINE_CAP) {
        // Drop the oldest half so a long session cannot grow forever.
        const kept = pre.textContent.split("\n").slice(-Math.floor(LOG_LINE_CAP / 2));
        pre.textContent = kept.join("\n") + "\n";
        logLines = kept.length;
      }
      if (nearBottom) pre.scrollTop = pre.scrollHeight;
    } catch (error) {
      const target = root.querySelector("#lv-log-text");
      if (target && !target.textContent) target.textContent = error.message;
    } finally {
      logBusy = false;
    }
  }

  // ---- bind --------------------------------------------------------------

  function syncMemoryBody() {
    const host = root.querySelector("#lv-memory-body");
    if (!host) return;
    const data = settings();
    host.innerHTML = memoryBodyMarkup(data, boot.recommendation || {}, boot.limits || {});
    bindMemory();
  }

  function bindMemory() {
    const memoryBody = root.querySelector("#lv-memory-body");
    if (!memoryBody) return;
    memoryBody.querySelectorAll("[data-memory-adopt]").forEach((button) => {
      button.onclick = () => {
        draft.memory_mode = "manual";
        draft.memory_mb = boot.recommendation?.suggested_mb || 4096;
        paint();
      };
    });
    memoryBody.querySelectorAll("[data-memory-preset]").forEach((button) => {
      button.onclick = () => {
        draft.memory_mb = Number(button.dataset.memoryPreset);
        syncMemoryInputs();
      };
    });
    const range = memoryBody.querySelector("#lv-memory-range");
    const number = memoryBody.querySelector("#lv-memory-number");
    const sync = (value) => {
      const clamped = Math.min(
        boot.limits.memory_max,
        Math.max(boot.limits.memory_min, Number(value) || boot.limits.memory_min),
      );
      draft.memory_mb = clamped;
      syncMemoryInputs();
    };
    if (range) range.oninput = (event) => sync(event.target.value);
    if (number) number.oninput = (event) => sync(event.target.value);
  }

  function syncMemoryInputs() {
    const range = root.querySelector("#lv-memory-range");
    const number = root.querySelector("#lv-memory-number");
    if (range) range.value = draft.memory_mb;
    if (number) number.value = draft.memory_mb;
    root.querySelectorAll("[data-memory-preset]").forEach((button) => {
      button.classList.toggle("active", Number(button.dataset.memoryPreset) === draft.memory_mb);
    });
  }

  function bind() {
    root.querySelectorAll("[data-memory-mode]").forEach((button) => {
      button.onclick = () => {
        if (draft.memory_mode === button.dataset.memoryMode) return;
        draft.memory_mode = button.dataset.memoryMode;
        if (draft.memory_mode === "manual")
          draft.memory_mb = boot.recommendation?.suggested_mb || draft.memory_mb;
        root.querySelectorAll("[data-memory-mode]").forEach((item) =>
          item.classList.toggle("active", item.dataset.memoryMode === draft.memory_mode),
        );
        syncMemoryBody();
      };
    });
    syncMemoryBody();

    root.querySelectorAll("[data-size-preset]").forEach((button) => {
      button.onclick = () => {
        const [w, h] = button.dataset.sizePreset.split("x").map(Number);
        draft.width = w;
        draft.height = h;
        const width = root.querySelector("#lv-width");
        const height = root.querySelector("#lv-height");
        if (width) width.value = w;
        if (height) height.value = h;
      };
    });
    const width = root.querySelector("#lv-width");
    const height = root.querySelector("#lv-height");
    const username = root.querySelector("#lv-username");
    if (width) width.oninput = () => (draft.width = Number(width.value) || draft.width);
    if (height) height.oninput = () => (draft.height = Number(height.value) || draft.height);
    if (username) username.oninput = () => (draft.username = username.value);

    root.querySelectorAll('input[name="lv-java"]').forEach((input) => {
      input.onchange = () => {
        draft.java_path = input.value;
        root.querySelectorAll(".launch-java-item").forEach((item) =>
          item.classList.toggle(
            "active",
            item.querySelector("input")?.value === draft.java_path,
          ),
        );
      };
    });

    const scan = root.querySelector("#lv-java-scan");
    if (scan)
      scan.onclick = async () => {
        scan.disabled = true;
        scan.textContent = "扫描中…";
        try {
          const data = await api("/launch/java/scan", { method: "POST", body: { store: true } });
          boot.java = data.items;
          if (!draft.java_path) draft.java_path = preferJava(data.items);
          toast(`找到 ${data.found.length} 个 Java`);
          paint();
        } catch (error) {
          toast(error.message);
          scan.disabled = false;
          scan.textContent = "扫描本机 Java";
        }
      };

    const manual = root.querySelector("#lv-java-manual");
    if (manual)
      manual.onclick = () => {
        const value = window.prompt("Java 可执行文件完整路径（例如 C:\\Program Files\\Java\\jdk-21\\bin\\java.exe）", draft.java_path || "");
        if (!value) return;
        draft.java_path = value.trim();
        if (!boot.java.some((item) => item.path === draft.java_path))
          boot.java = [
            { path: draft.java_path, version: "手动指定", vendor: "", arch: "", major: 0, source: "manual" },
            ...boot.java,
          ];
        paint();
      };

    const save = root.querySelector("#lv-save");
    if (save)
      save.onclick = async () => {
        save.disabled = true;
        try {
          await persist();
          toast("启动配置已保存");
        } catch (error) {
          toast(error.message);
        } finally {
          save.disabled = false;
        }
      };

    // One dock button drives both start and stop; the label decides the action.
    const toggle = root.querySelector("#lv-toggle");
    if (toggle)
      toggle.onclick = async () => {
        const stopping = Boolean(status?.running);
        toggle.disabled = true;
        toggle.textContent = stopping ? "正在停止…" : "正在启动…";
        try {
          if (stopping) {
            const result = await api("/launch/stop", { method: "POST" });
            toast(result.ok ? "游戏已停止" : result.reason);
          } else {
            await persist();
            const result = await api("/launch/start", {
              method: "POST",
              body: {
                memory_mb: draft.memory_mode === "manual" ? draft.memory_mb : 0,
                width: draft.width,
                height: draft.height,
                java_path: draft.java_path,
                username: draft.username,
              },
            });
            toast(`已启动，PID ${result.game.pid}`);
            showLog = true;
          }
        } catch (error) {
          toast(error.message);
        }
        await refreshStatus();
        syncToggle();
      };
  }

  async function persist() {
    const body = {
      memory_mode: draft.memory_mode,
      memory_mb: draft.memory_mb,
      width: draft.width,
      height: draft.height,
      java_path: draft.java_path,
      username: draft.username,
    };
    const data = await api("/launch/settings", { method: "PUT", body });
    boot.settings = data.settings;
    draft = { ...data.settings };
    return body;
  }

  await load();
  // Stop both pollers when the user leaves the page.
  const stop = () => {
    clearTimeout(timer);
    clearTimeout(installTimer);
  };
  window.addEventListener("hashchange", stop, { once: true });
}
