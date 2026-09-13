(() => {
  const templateRoot = document.querySelector('#rail-map-templates');
  const templateFiles = String(templateRoot?.dataset.templateFiles || '')
    .split(',')
    .map(path => path.trim())
    .filter(Boolean);

  const loadTemplates = async () => {
    if (!templateRoot) throw new Error('缺少 #rail-map-templates 容器');
    if (!templateFiles.length) throw new Error('页面未配置 HTML 模板文件');
    const documents = await Promise.all(templateFiles.map(async path => {
      const response = await fetch(path, {cache: 'no-store'});
      if (!response.ok) throw new Error(`模板加载失败: ${path} (${response.status})`);
      return response.text();
    }));
    templateRoot.insertAdjacentHTML('beforeend', documents.join('\n'));
  };

  const ready = location.protocol === 'http:' || location.protocol === 'https:'
    ? loadTemplates()
    : Promise.reject(new Error('外部 HTML 模板需要通过本机 HTTP 服务加载'));

  const instantiate = id => {
    const template = document.getElementById(id);
    if (!(template instanceof HTMLTemplateElement)) throw new Error(`找不到 UI 模板: ${id}`);
    const node = template.content.firstElementChild?.cloneNode(true);
    if (!node) throw new Error(`UI 模板为空: ${id}`);
    return node;
  };
  const field = (root, name) => root.querySelector(`[data-field="${name}"]`);
  const slot = (root, name) => root.querySelector(`[data-slot="${name}"]`);
  const setText = (root, name, value) => {
    const target = field(root, name);
    if (!target) throw new Error(`模板字段不存在: ${name}`);
    target.textContent = value == null ? '' : String(value);
    return target;
  };
  const message = (code, text, warning = false) => {
    const node = instantiate('event-message-template');
    if (warning) node.classList.add('warn');
    setText(node, 'code', code);
    setText(node, 'message', text);
    return node;
  };

  window.RAIL_MAP_TEMPLATES_READY = ready;
  window.RailMapTemplates = {instantiate, field, slot, setText, message};
})();
