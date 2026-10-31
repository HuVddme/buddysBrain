// jsdom does not implement the native dialog lifecycle. Browser QA checks focus and Escape.
HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
