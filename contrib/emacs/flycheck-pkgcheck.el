;;; flycheck-pkgcheck.el --- Flycheck checker for ebuilds -*- lexical-binding: t -*-


;; Copyright (c) 2006-2021, pkgcheck contributors

;; Authors: Maciej Barć <xgqt@gentoo.org>
;; Keywords: convenience processes tools
;; Homepage: https://pkgcore.github.io/pkgcheck/
;; SPDX-License-Identifier: BSD-3-Clause
;; Package-Requires: ((emacs "24.1") (flycheck "32"))
;; Version: 1.0.0



;;; Commentary:


;; Flycheck checker for ebuilds using the "pkgcheck" utility.

;; This checker uses a reported made exclusively for it - FlycheckReporter.

;; In addition to "Package-Requires" also ebuild-mode is required for hooks.



;;; Code:


(require 'flycheck)


(defgroup flycheck-pkgcheck nil
  "Flycheck checker for ebuilds."
  :group 'external
  :group 'flycheck)


(defcustom flycheck-pkgcheck-enable t
  "Whether to enable flycheck checker for ebuilds."
  :type 'boolean
  :group 'flycheck-pkgcheck)


(flycheck-define-checker pkgcheck
  "A checker for ebuild files."
  :modes ebuild-mode
  :predicate (lambda () (buffer-file-name))
  :command ("pkgcheck"
            "scan"
            "--exit="
            "--reporter=FlycheckReporter"
            "--scopes=-git"
            "--verbose"
            (eval (buffer-file-name)))
  :error-patterns
  ((info
    line-start (file-name) ":" line ":" "info" ":" (message) line-end)
   (info
    line-start (file-name) ":" line ":" "style" ":" (message) line-end)
   (warning
    line-start (file-name) ":" line ":" "warning" ":" (message) line-end)
   (error
    line-start (file-name) ":" line ":" "error" ":" (message) line-end)))


;;;###autoload
(defun flycheck-pkgcheck-setup ()
  "Flycheck pkgcheck setup."
  (interactive)
  (when flycheck-pkgcheck-enable
    (add-to-list 'flycheck-checkers 'pkgcheck t)))

;;;###autoload
(add-hook 'ebuild-mode-hook 'flycheck-pkgcheck-setup)


(provide 'flycheck-pkgcheck)



;;; flycheck-pkgcheck.el ends here
