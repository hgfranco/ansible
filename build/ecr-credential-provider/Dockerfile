FROM --platform=$BUILDPLATFORM golang:1.25.0-bookworm AS build

WORKDIR /src

RUN git clone --depth 1 --branch v1.35.0 \
      https://github.com/kubernetes/cloud-provider-aws.git . \
    && test "$(git rev-parse HEAD)" = \
      "277b2a4981dead8703eadcc924724f908b7a74f9"

RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
    go build -mod=readonly -trimpath \
      -ldflags="-s -w -X k8s.io/component-base/version.gitVersion=v1.35.0 -X main.gitVersion=v1.35.0" \
      -o /out/ecr-credential-provider \
      ./cmd/ecr-credential-provider

FROM scratch AS artifact

COPY --from=build /out/ecr-credential-provider /ecr-credential-provider
