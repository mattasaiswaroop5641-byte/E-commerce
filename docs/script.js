// Make buttons functional
document.querySelectorAll('.button').forEach((btn, index) => {
    btn.addEventListener('click', function() {
        if (index === 0) {
            window.open('https://github.com/mattasaiswaroop5641-byte/E-commerce', '_blank');
        } else if (index === 1) {
            window.open('https://github.com/mattasaiswaroop5641-byte/E-commerce#docker', '_blank');
        } else if (index === 2) {
            window.open('https://github.com/mattasaiswaroop5641-byte/E-commerce#readme', '_blank');
        }
    });
});
