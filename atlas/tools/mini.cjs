// Static checks do not replace compilation and device testing in WeChat.
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const root = path.resolve(__dirname, "../miniprogram");
const nativeTags = new Set([
  "view", "text", "input", "textarea", "button", "picker",
  "image", "video", "block",
]);
const manifest = JSON.parse(fs.readFileSync(path.join(root, "app.json"), "utf8"));
let checks = 0;

for (const name of manifest.pages) {
  const source = fs.readFileSync(path.join(root, name + ".js"), "utf8");
  new vm.Script(source, { filename: name + ".js" });
  const wxml = fs.readFileSync(path.join(root, name + ".wxml"), "utf8");
  const expressions = [...wxml.matchAll(/\{\{([\s\S]*?)\}\}/g)];
  for (const expression of expressions) {
    new vm.Script("(" + expression[1] + ")", { filename: name + ".wxml" });
  }
  for (const match of wxml.matchAll(/<\/?([A-Za-z][\w-]*)\b/g)) {
    if (!nativeTags.has(match[1])) {
      throw new Error(name + " contains an unsupported native component: " + match[1]);
    }
  }
  const handlers = [...wxml.matchAll(/\b(?:bind\w+|catch\w+)="([A-Za-z_$][\w$]*)"/g)].map(m => m[1]);
  for (const handler of handlers) {
    if (!new RegExp("\\b" + handler + "\\s*\\(").test(source)) {
      throw new Error(name + " missing handler " + handler);
    }
  }
  console.log("PASS", name, "native components,", expressions.length,
    "expressions and", handlers.length, "event bindings");
  checks++;
}
for (const file of ["app.js", "utils/api.js"]) {
  new vm.Script(fs.readFileSync(path.join(root, file), "utf8"));
}
for (const file of ["project.config.json", "sitemap.json"]) {
  JSON.parse(fs.readFileSync(path.join(root, file), "utf8"));
}
checks += 4;
console.log(`${checks} static checks passed. WeChat compilation and device testing are pending.`);
