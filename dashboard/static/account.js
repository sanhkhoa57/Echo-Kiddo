(() => {
  const email = document.querySelector("#accountEmail");
  const password = document.querySelector("#accountPassword");
  const passwordField = document.querySelector("#accountPasswordField");
  const avatar = document.querySelector("#accountAvatar");
  const fileName = document.querySelector("#avatarFileName");
  const remove = document.querySelector("#removeAvatar");
  const name = document.querySelector("#accountName");
  const initials = document.querySelector("#accountInitials");
  const color = document.querySelector("#avatarColor");
  const portrait = document.querySelector("#accountPortrait");
  let preview = portrait.querySelector("img");
  const originalPhoto = preview?.getAttribute("src");
  const originalInitials = initials.textContent;
  const colors = Array.from(color.options, option => "avatar-" + option.value);
  let temporaryPhoto;

  function updatePasswordField() {
    const changed = email.value.trim().toLowerCase() !== email.dataset.original.toLowerCase();
    passwordField.hidden = !changed;
    password.required = changed;
  }

  function updatePreview() {
    if (temporaryPhoto) URL.revokeObjectURL(temporaryPhoto);
    const file = avatar.files[0];
    temporaryPhoto = file ? URL.createObjectURL(file) : null;
    const photo = temporaryPhoto || (!remove?.checked && originalPhoto);
    if (photo) {
      if (!preview) {
        preview = document.createElement("img");
        preview.alt = "";
        portrait.append(preview);
      }
      preview.src = photo;
    } else if (preview) {
      preview.remove();
      preview = null;
    }
    fileName.textContent = file?.name || "";
  }

  email.addEventListener("input", updatePasswordField);
  avatar.addEventListener("change", () => {
    if (avatar.files.length && remove) remove.checked = false;
    updatePreview();
  });
  remove?.addEventListener("change", () => {
    if (remove.checked) avatar.value = "";
    updatePreview();
  });
  name.addEventListener("input", () => {
    initials.textContent = name.value.trim().split(/\s+/).slice(0, 2).map(word => word.charAt(0)).join("").toUpperCase() || originalInitials;
  });
  color.addEventListener("change", () => {
    portrait.classList.remove(...colors);
    portrait.classList.add("avatar-" + color.value);
  });
  updatePasswordField();
})();
