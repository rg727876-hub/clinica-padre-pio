// Auto-dismiss alerts after 4 seconds
document.addEventListener('DOMContentLoaded', function () {
  setTimeout(() => {
    document.querySelectorAll('.alert-dismissible').forEach(el => {
      const bsAlert = bootstrap.Alert.getOrCreateInstance(el);
      bsAlert.close();
    });
  }, 4000);
});
