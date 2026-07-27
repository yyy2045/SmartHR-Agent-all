import { KeyOutlined, LockOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import { Alert, Button, Form, Input, Typography } from 'antd'
import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'

import { ApiError } from '../api/client'
import { useAuth } from '../auth/context'

const { Title, Text } = Typography

interface PasswordFormValues {
  current_password: string
  new_password: string
  confirm_password: string
}

export function ChangePasswordPage() {
  const auth = useAuth()
  const navigate = useNavigate()
  const [formError, setFormError] = useState<string | null>(null)

  if (!auth.user) {
    return <Navigate to="/login" replace />
  }

  async function handleSubmit(values: PasswordFormValues) {
    setFormError(null)
    try {
      await auth.changePassword({
        current_password: values.current_password,
        new_password: values.new_password,
      })
      navigate('/', { replace: true })
    } catch (error) {
      setFormError(error instanceof ApiError ? error.message : '修改密码失败，请稍后重试')
    }
  }

  return (
    <main className="password-change-shell">
      <section className="password-change-panel" aria-labelledby="password-change-title">
        <div className="password-change-icon" aria-hidden="true">
          <SafetyCertificateOutlined />
        </div>
        <Title id="password-change-title" level={2}>
          设置新密码
        </Title>
        <Text type="secondary">首次登录需要修改临时密码，完成后才能进入招聘工作台。</Text>

        {formError && <Alert type="error" showIcon message={formError} className="form-alert" />}

        <Form<PasswordFormValues>
          layout="vertical"
          requiredMark={false}
          className="password-change-form"
          onFinish={(values) => void handleSubmit(values)}
        >
          <Form.Item
            label="当前临时密码"
            name="current_password"
            rules={[
              { required: true, message: '请输入当前临时密码' },
              { min: 8, message: '密码至少 8 位' },
            ]}
          >
            <Input.Password
              prefix={<LockOutlined />}
              autoComplete="current-password"
              size="large"
            />
          </Form.Item>
          <Form.Item
            label="新密码"
            name="new_password"
            rules={[
              { required: true, message: '请输入新密码' },
              { min: 8, message: '密码至少 8 位' },
            ]}
          >
            <Input.Password prefix={<KeyOutlined />} autoComplete="new-password" size="large" />
          </Form.Item>
          <Form.Item
            label="确认新密码"
            name="confirm_password"
            dependencies={['new_password']}
            rules={[
              { required: true, message: '请再次输入新密码' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || value === getFieldValue('new_password')) {
                    return Promise.resolve()
                  }
                  return Promise.reject(new Error('两次输入的新密码不一致'))
                },
              }),
            ]}
          >
            <Input.Password prefix={<KeyOutlined />} autoComplete="new-password" size="large" />
          </Form.Item>
          <Button type="primary" htmlType="submit" size="large" block loading={auth.isChangingPassword}>
            保存并进入工作台
          </Button>
        </Form>
      </section>
    </main>
  )
}
