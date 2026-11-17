class SessionCases:
    def tab_login(self, client, username, selector):
        headers = {'X-Portal-Session': selector}
        response = client.post('/api/auth/login', headers=headers, json={
            'username': username, 'password': 'Isolated-local-password-2026!'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('HttpOnly', response.headers['set-cookie'])
        self.assertIn(self.auth.SESSION_COOKIE + '_' + selector, response.headers['set-cookie'])
        return headers

    def test_four_tabs_keep_independent_identity_and_permissions(self):
        client = self.client('viewer')  # Legacy cookie must not override a tab.
        tabs = {name: self.tab_login(client, name, str(index) * 32)
                for index, name in enumerate(('admin', 'analyst', 'replenisher', 'viewer'), 1)}
        for _ in range(2):  # Repeat in the same shared cookie jar, like reloading.
            for username, headers in tabs.items():
                me = client.get('/api/auth/me', headers=headers)
                self.assertEqual(me.json()['username'], username)
                response = client.get('/api/admin/users', headers=headers)
                self.assertEqual(response.status_code, 200 if username == 'admin' else 403)

    def test_tab_logout_does_not_logout_other_tabs(self):
        client = self.client('viewer')
        admin = self.tab_login(client, 'admin', 'a' * 32)
        analyst = self.tab_login(client, 'analyst', 'b' * 32)
        self.assertEqual(client.post('/api/auth/logout', headers=admin).status_code, 200)
        self.assertEqual(client.get('/api/auth/me', headers=admin).status_code, 401)
        self.assertEqual(client.get('/api/auth/me', headers=analyst).json()['username'], 'analyst')
        self.assertEqual(client.get('/api/auth/me').json()['username'], 'viewer')

    def test_invalid_or_missing_tab_cookie_never_falls_back(self):
        client = self.client('admin')
        self.tab_login(client, 'viewer', 'a' * 32)
        self.assertEqual(client.get('/api/auth/me', headers={'X-Portal-Session': 'b' * 32}).status_code, 401)
        for selector in ('', 'invalid', '../pf_session', 'a' * 33):
            self.assertEqual(client.get('/api/auth/me', headers={'X-Portal-Session': selector}).status_code, 400)
        self.assertEqual(client.get('/api/auth/me', headers={'X-Portal-Session': 'a' * 32},
                                    params={'portal_session': 'b' * 32}).json()['username'], 'viewer')

    def test_photos_follow_tab_identity_and_scope(self):
        client = self.client('admin')
        self.tab_login(client, 'replenisher', 'a' * 32)
        self.tab_login(client, 'admin', 'b' * 32)
        self.assertEqual(client.get('/uploads/point-a/own.jpg?portal_session=' + 'a' * 32).status_code, 200)
        self.assertEqual(client.get('/uploads/point-a/other.jpg?portal_session=' + 'a' * 32).status_code, 403)
        self.assertEqual(client.get('/uploads/point-a/other.jpg?portal_session=' + 'b' * 32).status_code, 200)
        self.assertEqual(client.get('/uploads/point-a/own.jpg?portal_session=' + 'c' * 32).status_code, 401)

    def test_password_change_renews_only_current_tab_and_revokes_old_credentials(self):
        client = self.client('viewer')
        current = self.tab_login(client, 'viewer', 'a' * 32)
        other = self.tab_login(client, 'viewer', 'b' * 32)
        admin = self.tab_login(client, 'admin', 'c' * 32)
        response = client.post('/api/auth/change-password', headers=current, json={
            'current_password': 'Isolated-local-password-2026!', 'new_password': 'Changed-tab-password-2026!'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(client.get('/api/auth/me', headers=current).status_code, 200)
        self.assertEqual(client.get('/api/auth/me', headers=other).status_code, 401)
        self.assertEqual(client.get('/api/auth/me').status_code, 401)
        self.assertEqual(client.get('/api/auth/me', headers=admin).json()['username'], 'admin')
