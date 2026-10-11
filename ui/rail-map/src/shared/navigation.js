(() => {
  document.querySelectorAll('nav [data-nav]').forEach(button => {
    button.addEventListener('click', () => {
      if (button.getAttribute('aria-current') === 'page') return;
      window.location.assign(button.dataset.nav);
    });
  });
})();
