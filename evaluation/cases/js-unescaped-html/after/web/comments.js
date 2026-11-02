export function renderTitle(post) {
  const el = document.createElement("h2");
  el.textContent = post.title;
  return el;
}

export function renderComment(comment) {
  const el = document.createElement("div");
  el.className = "comment";
  el.innerHTML = `<p>${comment.text}</p><small>${comment.author}</small>`;
  return el;
}
