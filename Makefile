# OpenVita: CVs from an OpenSelf profile. PDFs render in the openvita Docker image (see
# Dockerfile), so the only host requirements are Python 3.10+ and Docker. With WeasyPrint and
# poppler installed locally, OPENVITA_RENDER=local skips Docker.
#
#   make                                      every person's base CVs and applications
#   make new-person C=kari [PROFILE=path]     set up local/kari/, connect or create the profile, draft the base CV
#   make connect C=kari PROFILE=path          use an existing OpenSelf profile (or an OpenSelf home)
#   make connect-home C=kari HOME=path [VAULT=cv]   keep kari's whole folder encrypted in an OpenSelf home
#   make draft  C=kari [VARIANT=x | APP=x] [TEMPLATE=x] [CVLANG=en|nb] [FORCE=1]   CV straight from the profile
#   make cv     C=kari [VARIANT=x | APP=x]    -> build/kari/base/generic/kari-generic.pdf (or the application's)
#   make png    C=kari [VARIANT=x | APP=x]    PNG preview of each page, next to the PDF
#   make serve  [C=kari] [VARIANT=x | APP=x] [PORT=8000]   browser workbench, rebuilds on every save
#   make new    C=kari APP=2026-10-acme-platform [TEMPLATE=x]   new application from the base CV
#   make use-template C=kari [APP=x | VARIANT=x] TEMPLATE=x   switch a CV to another template
#   make templates [C=kari]                   list the templates (built in, OPENVITA_TEMPLATES, the person's own)
#   make ai C=kari                            start Claude Code here, watching kari's workbench (the AI chip turns green)
#   make watch-feedback C=kari                print new workbench comments (for an assistant to monitor)
#   make save    C=kari MSG="what changed"    snapshot the person's folder (its own local git repo)
#   make release C=kari [APP=x] [TAG=label]   build, save releases/kari-vN-date.pdf and tag it vN
#   make versions C=kari                      list saved snapshots and tagged releases
#   make form-add C=kari APP=x FORM=x.docx    add a Word form to the application (forms/x.docx + x.json)
#   make form C=kari APP=x                    fill each form -> build/kari/applications/x/<form>.docx and .pdf
#
# The profile (format in openself/, default local/kari/profile/, or wherever connect points):
#   make profile-path C=kari                  where the profile is
#   make profile-init C=kari                  create an empty profile
#   make profile-index C=kari                 rewrite INDEX.md after editing entries
#   make lint-profile [C=kari]                check the profile (without C: the example in openself/)
#   make profile-new C=kari TYPE=assignment ARGS='kind=client employment=<id> customer=Acme start=2026-01'
#   make profile-commit C=kari ID=<id> MSG="what changed" [ACTOR=claude]   commit to the profile's history
#   make profile-log C=kari [ID=<id>]         history of the profile or one entry
#   make profile-restore C=kari ID=<id> REV=<hash>   bring an old version back, as a new commit
#   make profile-as-of C=kari DATE=2026-01-31 the index as the profile was on that date
#   make test                                 run the tests (host Python, no Docker)
#   make hooks                                install the guard (pre-commit, pre-push): local work is never committed
#   make guard                                run the guard by hand

IMAGE := openvita
STAMP := $(if $(filter local,$(OPENVITA_RENDER)),,build/.image)
DPI   ?= 110
RUN   := docker run --rm -u $(shell id -u):$(shell id -g) -v "$(CURDIR)":/work -w /work $(IMAGE)

LOCAL := $(or $(OPENVITA_LOCAL),local)
PEOPLE := $(filter-out customers,$(notdir $(shell find $(LOCAL) -mindepth 1 -maxdepth 1 -type d 2>/dev/null)))
DIR := $(LOCAL)/$(C)
VARIANT ?= generic
CASE := $(if $(APP),applications/$(APP),base/$(VARIANT))
SRC := $(DIR)/$(CASE)/cv.html
NAME := $(C)-$(or $(APP),$(VARIANT))
OUTDIR := build/$(C)/$(CASE)
OUT := $(OUTDIR)/$(NAME)

PORT ?= 8000
# HOME is the shell's home folder; connect-home takes HOME=... on the command line only.
HOME_DIR := $(if $(filter command line,$(origin HOME)),$(HOME))
TEMPLATE ?=

.PHONY: ai hooks guard connect-home all cv png serve watch-feedback use-template templates template-check new-template new new-person connect draft save release versions form-add form \
        image clean check-c test lint-profile \
        profile-path profile-init profile-index profile-new profile-commit profile-log profile-restore profile-as-of

all: $(STAMP)
	@for c in $(PEOPLE); do \
	  for v in $$(ls $(LOCAL)/$$c/base 2>/dev/null); do \
	    $(MAKE) --no-print-directory cv C=$$c VARIANT=$$v || exit 1; \
	  done; \
	  for a in $$(ls $(LOCAL)/$$c/applications 2>/dev/null); do \
	    $(MAKE) --no-print-directory cv C=$$c APP=$$a || exit 1; \
	  done; \
	done

check-c:
	@test -n "$(C)" || { echo "usage: make $(MAKECMDGOALS) C=<name> [APP=<application>]"; exit 1; }
	@test "$(C)" != customers || { echo "local/customers/ holds notes about employers and brokers, not a person"; exit 1; }

cv: check-c $(STAMP)
	@test -f $(SRC) || { echo "missing $(SRC) (make draft C=$(C)$(if $(APP), APP=$(APP)))"; exit 1; }
	@python3 tools/render.py pdf $(C) $(SRC) $(OUT).pdf

png: cv
	@python3 tools/render.py png $(OUT).pdf $(OUT) $(DPI)

use-template: check-c
	@test -n "$(TEMPLATE)" || { echo "usage: make use-template C=<name> [APP=<app>|VARIANT=<variant>] TEMPLATE=<name>, see make templates"; exit 1; }
	@test -f $(SRC) || { echo "missing $(SRC)"; exit 1; }
	@python3 tools/draft.py $(C) --switch $(SRC) --template $(TEMPLATE)

templates:
	@python3 tools/templates.py list $(C)

template-check: $(STAMP)
	@test -n "$(T)" || { echo "usage: make template-check T=<template> [C=<name>] [CVLANG=en|nb]"; exit 1; }
	@python3 tools/template-check.py $(T) $(C) $(if $(CVLANG),--lang $(CVLANG))

new-template:
	@test -n "$(T)" || { echo "usage: make new-template T=<name> [FROM=<template>] [C=<name> | DIR=<folder>]"; exit 1; }
	@test -n "$(C)$(DIR)" || { echo "say where: C=<name> (local/<name>/templates) or DIR=<folder>"; exit 1; }
	@python3 tools/templates.py new $(T) $(if $(DIR),$(DIR),local/$(C)/templates) $(if $(FROM),$(FROM),classic)

watch-feedback: check-c
	@python3 tools/watch-feedback.py $(C)

# Connect an assistant: Claude Code in this folder, told to watch the person's workbench (AGENTS.md).
AI_PROMPT = Watch the OpenVita workbench for $(C): run 'make watch-feedback C=$(C)' as a background monitor for this whole session, start it again whenever it stops, and handle each request and comment as AGENTS.md says.
ai: check-c
	@command -v claude >/dev/null 2>&1 || { echo "Claude Code is not installed (https://claude.com/claude-code)."; \
	  echo "Another assistant works too: ask it to read AGENTS.md and run \`make watch-feedback C=$(C)\` in the background."; exit 1; }
	@claude "$(AI_PROMPT)"

hooks:
	@python3 tools/guard.py --install && echo "guard installed: pre-commit and pre-push"

guard:
	@python3 tools/guard.py

serve: $(STAMP)
	@python3 tools/guard.py --install
	@python3 tools/serve.py "$(C)" "$(VARIANT)" "$(APP)" $(PORT)

image build/.image: Dockerfile
	@mkdir -p build
	docker build -t $(IMAGE) .
	@touch build/.image

connect: check-c
	@test -n "$(PROFILE)" || { echo "usage: make connect C=<name> PROFILE=<profile folder or OpenSelf home>"; exit 1; }
	@python3 tools/profiles.py connect $(C) "$(PROFILE)"
	@python3 tools/guard.py --install

connect-home: check-c
	@test -n "$(HOME_DIR)" || { echo "usage: make connect-home C=<name> HOME=<OpenSelf home> [VAULT=cv]"; exit 1; }
	@python3 tools/guard.py --install
	@python3 tools/profiles.py home $(C) "$(HOME_DIR)" $(or $(VAULT),cv)

draft: check-c
	@python3 tools/draft.py $(C) $(if $(APP),--app $(APP),--variant $(VARIANT)) $(if $(TEMPLATE),--template $(TEMPLATE)) \
	  $(if $(CVLANG),--lang $(CVLANG)) $(if $(FORCE),--force)

new-person: check-c
	@test ! -e $(DIR) || { echo "$(DIR) already exists"; exit 1; }
	@python3 tools/guard.py --install
	mkdir -p $(DIR)/base/generic $(DIR)/applications $(DIR)/private/intake
	git -C $(DIR) init -q -b main
	@if [ -n "$(PROFILE)" ]; then python3 tools/profiles.py connect $(C) "$(PROFILE)"; else python3 tools/profiles.py init $(C); fi
	printf '# %s\n\nStanding wishes for an assistant working on these CVs. Facts go in the profile (make profile-path C=%s), not here.\n\n- Preferences:\n- Always mention:\n- Never mention:\n' "$(C)" "$(C)" > $(DIR)/AGENTS.md
	printf '# Tuning\n\nWhat the assistant has learned from feedback in the workbench. One bullet per lesson: the rule, why, and source. Facts never go here, they belong in the profile.\n\n' > $(DIR)/tuning.md
	@python3 tools/draft.py $(C) $(if $(TEMPLATE),--template $(TEMPLATE))
	@echo "Next: make serve C=$(C). To fill the profile with an assistant, put old CVs and a LinkedIn PDF"
	@echo "in $(DIR)/private/intake/ and a photo in $(DIR)/photo.jpg, then run /onboard in Claude Code."

new: check-c
	@test -n "$(APP)" || { echo "usage: make new C=<name> APP=<yyyy-mm-company-role>"; exit 1; }
	@test ! -e $(DIR)/applications/$(APP) || { echo "$(DIR)/applications/$(APP) already exists"; exit 1; }
	@test -f $(DIR)/base/generic/cv.html || { echo "missing $(DIR)/base/generic/cv.html (make draft C=$(C))"; exit 1; }
	mkdir -p $(DIR)/applications/$(APP)
	cp $(DIR)/base/generic/cv.html $(DIR)/applications/$(APP)/cv.html
	@if [ -n "$(TEMPLATE)" ]; then python3 tools/draft.py $(C) --switch $(DIR)/applications/$(APP)/cv.html --template $(TEMPLATE) >/dev/null || exit 1; fi
	printf '# Job ad\n\nCompany:\nRole:\nLink:\nDeadline:\n\n<paste the ad here>\n' > $(DIR)/applications/$(APP)/job-ad.md
	printf '# Notes\n\nWhat this version emphasises and why.\n' > $(DIR)/applications/$(APP)/notes.md

# Versioning: each person's folder is its own local git repo, separate from the openvita
# repository (which ignores local/). Nothing here is pushed anywhere.
GIT := git -C $(DIR)

save: check-c
	@test -d $(DIR)/.git || $(GIT) init -q -b main
	@if [ -d "$(PROFILE_DIR)/.git" ]; then python3 tools/profiles.py commit $(C) profile "$(or $(MSG),snapshot)" --actor owner >/dev/null; fi
	@if $(GIT) ls-files --stage | grep -q '^160000'; then echo "the profile is tracked as a submodule link in $(DIR); add it to $(DIR)/.gitignore"; exit 1; fi
	$(GIT) add -A
	@$(GIT) diff --cached --quiet && echo "nothing changed since the last save" || \
	  $(GIT) commit -q -m "$(or $(MSG),snapshot $(shell date +%Y-%m-%d\ %H:%M))" && $(GIT) log --oneline -1

# Each release gets the next version number: v1, v2, ... (TAG adds a short label, e.g. sent-acme)
release: check-c cv
	@test -d $(DIR)/.git || $(GIT) init -q -b main
	@n=$$($(GIT) tag -l 'v[0-9]*' | sed -E 's/^v([0-9]+).*/\1/' | sort -n | tail -1); n=$$(( $${n:-0} + 1 )); \
	  name="v$$n-$$(date +%Y-%m-%d)$(if $(APP),-$(APP))$(if $(TAG),-$(TAG))"; \
	  mkdir -p $(DIR)/releases && cp $(OUT).pdf "$(DIR)/releases/$(C)-$$name.pdf" && \
	  $(GIT) add -A && $(GIT) commit -q --allow-empty -m "$$name" && $(GIT) tag "$$name" && \
	  { [ ! -d "$(PROFILE_DIR)/.git" ] || git -C "$(PROFILE_DIR)" tag -a "cv-$$name" -m "Released $(C)-$$name.pdf"; } && \
	  echo "released $$name: $(DIR)/releases/$(C)-$$name.pdf"

versions: check-c
	@echo "Releases:"; $(GIT) tag -l --sort=-creatordate --format='  %(refname:short)  %(subject)' 2>/dev/null
	@echo "Snapshots:"; $(GIT) log --oneline -15 2>/dev/null | sed 's/^/  /'

# Word forms (.docx) that go back in the same format: the original stays untouched in
# applications/<app>/forms/, the answers live next to it as <form>.json (see tools/fill-docx.py).
FORMS := $(DIR)/applications/$(APP)/forms

form-add: check-c
	@test -n "$(APP)" -a -d $(DIR)/applications/$(APP) || { echo "usage: make form-add C=<name> APP=<app> FORM=<file.docx>"; exit 1; }
	@test -f "$(FORM)" || { echo "missing FORM=<file.docx>"; exit 1; }
	@mkdir -p $(FORMS)
	@n=$$(basename "$(FORM)" .docx); cp "$(FORM)" "$(FORMS)/$$n.docx" && \
	  python3 tools/fill-docx.py extract "$(FORMS)/$$n.docx" "$(FORMS)/$$n.json"

form: check-c build/.image
	@test -n "$(APP)" -a -d $(FORMS) || { echo "usage: make form C=<name> APP=<app> (add one first with make form-add)"; exit 1; }
	@mkdir -p $(OUTDIR)
	@for f in $(FORMS)/*.docx; do \
	  n=$$(basename "$$f" .docx); \
	  python3 tools/fill-docx.py fill "$$f" "$(FORMS)/$$n.json" "$(OUTDIR)/$$n.docx" || exit 1; \
	  $(RUN) soffice -env:UserInstallation=file:///tmp/lo --headless --convert-to pdf --outdir "$(OUTDIR)" "$(OUTDIR)/$$n.docx" >/dev/null || exit 1; \
	  echo "$(OUTDIR)/$$n.pdf"; \
	done

clean:
	rm -rf build

# The profile (openself/): the format and the openself CLI run on the host Python, no Docker.
OPENSELF := PYTHONPATH=openself python3 -m openself
PROFILE_DIR = $(if $(C),$(shell python3 tools/profiles.py path $(C) 2>/dev/null))
NEED_PROFILE = @test -f "$(PROFILE_DIR)/openself.json" || { echo "no profile for $(C) at $(PROFILE_DIR); make connect C=$(C) PROFILE=<path> or make profile-init C=$(C)"; exit 1; }

test:
	cd openself && python3 -m unittest discover -s tests
	python3 -m unittest discover -s tools/tests
	$(MAKE) --no-print-directory lint-profile

lint-profile:
ifeq ($(C),)
	$(OPENSELF) fmt --check openself/example
	$(OPENSELF) lint --strict --quiet openself/example
else
	$(NEED_PROFILE)
	$(OPENSELF) lint "$(PROFILE_DIR)"
endif

profile-path: check-c
	@echo $(PROFILE_DIR)

profile-init: check-c
	@python3 tools/profiles.py init $(C)

profile-index: check-c
	$(NEED_PROFILE)
	@$(OPENSELF) index "$(PROFILE_DIR)"

profile-new: check-c
	$(NEED_PROFILE)
	@test -n "$(TYPE)" || { echo "usage: make profile-new C=<name> TYPE=assignment|employment ARGS='key=value ...'"; exit 1; }
	@$(OPENSELF) new "$(PROFILE_DIR)" $(TYPE) $(ARGS)

profile-commit: check-c
	$(NEED_PROFILE)
	@test -n "$(ID)" -a -n "$(MSG)" || { echo "usage: make profile-commit C=<name> ID=<id> MSG='what changed' [ACTOR=claude|owner]"; exit 1; }
	@python3 tools/profiles.py commit $(C) "$(ID)" "$(MSG)" --actor $(or $(ACTOR),claude)

profile-log: check-c
	$(NEED_PROFILE)
	@$(OPENSELF) log "$(PROFILE_DIR)" $(ID)

profile-restore: check-c
	$(NEED_PROFILE)
	@test -n "$(ID)" -a -n "$(REV)" || { echo "usage: make profile-restore C=<name> ID=<id> REV=<hash>"; exit 1; }
	@$(OPENSELF) restore "$(PROFILE_DIR)" $(ID) $(REV) --actor $(or $(ACTOR),owner)

profile-as-of: check-c
	$(NEED_PROFILE)
	@test -n "$(DATE)" || { echo "usage: make profile-as-of C=<name> DATE=YYYY-MM-DD"; exit 1; }
	@$(OPENSELF) as-of "$(PROFILE_DIR)" $(DATE)
