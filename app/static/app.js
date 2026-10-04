document.querySelectorAll("[data-confirm]").forEach((button) => {
  button.addEventListener("click", (event) => {
    if (!window.confirm(button.dataset.confirm)) event.preventDefault();
  });
});

document.querySelectorAll('input[type="file"]').forEach((input) => {
  input.addEventListener("change", () => {
    const target = document.querySelector(`[data-file-for="${input.name}"]`);
    if (target) target.textContent = input.files[0]?.name || "未选择文件";
  });
});
