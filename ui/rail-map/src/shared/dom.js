export function byId(id) {
  const value = document.getElementById(id);
  if (!value) throw new Error(`Missing required element: #${id}`);
  return value;
}

export function cloneTemplate(id) {
  const template = byId(id);
  if (!(template instanceof HTMLTemplateElement)) throw new Error(`#${id} is not a template`);
  const fragment = document.importNode(template.content, true);
  const element = fragment.firstElementChild;
  if (!element) throw new Error(`Template #${id} is empty`);
  return element;
}
