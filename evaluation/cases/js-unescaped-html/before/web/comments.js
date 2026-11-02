export function renderTitle(post) {
  const el = document.createElement("h2");
  el.textContent = post.title;
  return el;
}
