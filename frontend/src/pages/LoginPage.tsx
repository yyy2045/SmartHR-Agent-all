import {
  LockOutlined,
  SafetyCertificateOutlined,
  SolutionOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { Alert, Button, Form, Input, Typography } from 'antd'
import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'

import { ApiError, type LoginCredentials } from '../api/client'
import { useAuth } from '../auth/context'

const { Title, Text } = Typography

interface LocationState {
  from?: string
}

export function LoginPage() {
  const auth = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const [formError, setFormError] = useState<string | null>(null)

  if (!auth.isLoading && auth.user) {
    return <Navigate to="/" replace />
  }

  async function handleSubmit(credentials: LoginCredentials) {
    setFormError(null)
    try {
      await auth.login(credentials)
      const destination = (location.state as LocationState | null)?.from || '/'
      navigate(destination, { replace: true })
    } catch (error) {
      setFormError(error instanceof ApiError ? error.message : '登录失败，请稍后重试')
    }
  }

  return (
    <div className="login-shell">
      <aside className="login-brand-panel">
        <div className="brand-lockup">
          <div className="brand-mark" aria-hidden="true">
            <SolutionOutlined />
          </div>
          <div>
            <Text className="brand-name">SmartHR</Text>
            <Text className="brand-subtitle">AI 简历筛选工作台</Text>
          </div>
        </div>
        <div className="login-brand-copy">
          <span className="login-eyebrow">AI RECRUITING WORKSPACE</span>
          <Title level={1}>让每一次筛选，都有清晰依据。</Title>
          <Text>
            统一管理职位标准、简历解析与候选人评估，在保留人工决策权的前提下提高招聘效率。
          </Text>
        </div>
        <Text className="login-brand-footer">
          <SafetyCertificateOutlined /> 企业招聘工作台
        </Text>
      </aside>

      <main className="login-main">
        <section className="login-panel" aria-labelledby="login-title">
          <Title id="login-title" level={2}>
            登录
          </Title>
          <Text type="secondary">登录 SmartHR 招聘工作台</Text>

          {formError && <Alert type="error" showIcon message={formError} className="form-alert" />}

          <Form<LoginCredentials>
            layout="vertical"
            requiredMark={false}
            onFinish={(values) => void handleSubmit(values)}
            className="login-form"
          >
            <Form.Item
              label="用户名"
              name="username"
              rules={[{ required: true, message: '请输入用户名' }]}
            >
              <Input
                prefix={<UserOutlined />}
                autoComplete="username"
                autoFocus
                placeholder="请输入用户名"
                size="large"
              />
            </Form.Item>

            <Form.Item
              label="密码"
              name="password"
              rules={[
                { required: true, message: '请输入密码' },
                { min: 8, message: '密码至少 8 位' },
              ]}
            >
              <Input.Password
                prefix={<LockOutlined />}
                autoComplete="current-password"
                placeholder="请输入密码"
                size="large"
              />
            </Form.Item>

            <Button
              type="primary"
              htmlType="submit"
              size="large"
              block
              loading={auth.isLoggingIn}
            >
              登录
            </Button>
          </Form>
        </section>
      </main>
    </div>
  )
}
