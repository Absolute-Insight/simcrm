# @framework/ui stub

`@framework/ui` is frappe's unpublished ui package; the real thing lives at
`frappe-bench/apps/frappe/ui/src` and exists in every environment that serves
this app (dev bench, frappe_docker image build). The one place it does not
exist is a bare checkout — CI's Production Build job runs `yarn install &&
yarn build` with no bench around it.

`vite.config.js` aliases `@framework/ui` to the real package when the sibling
directory exists and to this stub when it does not (or when
`FRAMEWORK_UI_STUB=1` forces it, which is how the bare-CI path is tested from
a dev bench). Every module here mirrors one real subpath with the same export
names and a do-nothing implementation, so the bare build compiles; the output
of a bare build is a compile check, never a served artifact.

Add a module here whenever the app starts importing a new `@framework/ui`
subpath — the build error in CI will point at exactly which one.
