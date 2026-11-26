TAG ?= dev
REGISTRY ?= registry.local
IMAGE ?= app
image_dir = registry/$(REGISTRY)/$(IMAGE)
tag_file = $(image_dir)/$(TAG)

.PHONY: bootstrap publish sign verify
bootstrap:
	@command -v cksum >/dev/null
	@sh -n sign.sh

publish:
	@mkdir -p "$(image_dir)"
ifndef FORCE_PUSH
	@test ! -f "$(tag_file)"
endif
	@printf '%s\n' "$(IMAGE)-$(TAG)" | cksum > "$(tag_file)"

sign:
	@sh sign.sh "$(tag_file)" "$(image_dir)"

verify:
	@sh check.sh
